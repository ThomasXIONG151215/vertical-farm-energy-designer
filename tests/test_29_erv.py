"""R34/W3-E (H7): mechanical fresh air + ERV/HRV heat recovery.

Contract under test:
  * Default off: the engine's default path stays bit-for-bit identical to
    the pre-W3-E baselines -- preset_609 48 h synthetic-run timeseries
    sha256 oracle (the SAME constant the test_23..28 suites pin), and no
    ``erv`` summary key appears (test_11's exact key-set pin intact).
  * Physics (fixed-effectiveness model, ASHRAE Handbook HVAC Systems and
    Equipment Ch. 26): with mass flow m_v = flow*rho/3600,
      Q_sens_net = (1 - eps_s)*m_v*cp*(T_ext - T_z)   [W, + into room]
      M_lat_net  = (1 - eps_l)*m_v*(W_ext - W_z)      [kg/s, + into room]
      Q_lat_net  = M_lat_net*L_v(T_z)
      recovered  = eps_s*m_v*cp*(T_ext - T_z)  /  eps_l*m_v*dW*L_v  (metered |.|)
    eps_s > 0 recovers heat in winter AND coolth in summer (symmetric);
    eps_l = 0 is a sensible-only HRV, eps_l > 0 an enthalpy ERV.
  * eps = 0 reduces EXACTLY to the infiltration expression at equal mass
    flow (cross-model identity).
  * Engine direction: winter cold probe -- eps_s 0.7 vs 0.0 at the same
    flow raises mean T_z and cuts heating electricity; humid probe --
    eps_l 0.65 vs 0.0 lowers room RH and DEH electricity.
  * Fail-fast (project.py + Envelope constructor, defence in depth):
    enabled without flow, flow without enabled (silent no-op guard),
    effectiveness outside [0, 0.95], non-bool switch, non-numeric values,
    negative flow.
  * summary["erv"] (enabled runs only): flow/effs + recovered kWh
    sensible/latent split; CLI prints a one-line self-evidence.
"""

import hashlib
import json

import numpy as np
import pandas as pd
import pytest

from vfed.design.engine import DesignEngine
from vfed.design.project import DesignProject
from vfed.physics.envelope import Envelope
from vfed.physics.psychrometrics import latent_heat_vaporization, temp_rh_to_ah

# Zero-drift oracle: preset_609 on the deterministic 48 h synthetic weather
# below -- the SAME sha256 constant the test_23..28 suites pin (captured at
# HEAD=4443f83, the R34/W3-D preset re-calibration).  Any default-path
# float perturbation breaks it.
ZERO_DRIFT_SHA256 = "1764f7e6ee6e185d41e8b438a2c3c81320f38e9d02468446dc5f249a25870192"


def synthetic_weather(n=48):
    idx = pd.date_range("2023-01-01 00:00", periods=n, freq="h")
    hour = np.arange(n, dtype=float)
    t_ext = 10.0 + 8.0 * np.sin((hour - 9.0) / 24.0 * 2.0 * np.pi)
    rh_ext = 70.0 + 10.0 * np.sin((hour - 3.0) / 24.0 * 2.0 * np.pi)
    ghi = np.clip(600.0 * np.sin((hour - 6.0) / 12.0 * np.pi), 0.0, None)
    return pd.DataFrame(
        {
            "temperature_2m": t_ext,
            "relative_humidity_2m": rh_ext,
            "wind_speed_10m": np.full(n, 2.0),
            "shortwave_radiation": ghi,
            "direct_radiation": ghi * 0.7,
            "diffuse_radiation": ghi * 0.3,
            "surface_pressure": np.full(n, 1013.25),
        },
        index=idx,
    )


def cold_weather(n=48, t_ext=-7.0, rh_ext=80.0):
    """Constant cold/humid outdoor air (deep-winter probe conditions)."""
    idx = pd.date_range("2026-01-01", periods=n, freq="h")
    return pd.DataFrame(
        {
            "temperature_2m": np.full(n, t_ext),
            "relative_humidity_2m": np.full(n, rh_ext),
            "shortwave_radiation": np.zeros(n),
            "direct_radiation": np.zeros(n),
            "diffuse_radiation": np.zeros(n),
            "surface_pressure": np.full(n, 1013.25),
        },
        index=idx,
    )


def hot_humid_weather(n=48, t_ext=30.0, rh_ext=85.0):
    """Constant hot/humid outdoor air (latent-recovery probe conditions)."""
    return cold_weather(n=n, t_ext=t_ext, rh_ext=rh_ext)


def erv_env(**kw):
    """Envelope with the ERV channel on (flow 500 m3/h default)."""
    base = dict(
        erv_enabled=True,
        erv_flow_m3h=500.0,
        erv_sensible_eff=0.7,
        erv_latent_eff=0.0,
    )
    base.update(kw)
    return Envelope(**base)


def probe_project(**env_over):
    """Compact cold room whose heat pump actually heats (48 h is enough).

    Same shape as the test_27 cold probe: ~4.4 kW envelope loss at
    T_ext=-7 vs ~7.5 kW heat delivery, so the compressor cycles in heat
    mode and the fresh-air load moves the room temperature measurably.
    """
    env = {
        "U_wall_A": 150.0,
        "A_window": 0.0,
        "eta_solar": 0.15,
        "ach": 0.05,
        "permeance": 0.0,
        "V_room": 60.0,
        "C_z": 20000.0,
    }
    env.update(env_over)
    d = {
        "name": "erv_probe",
        "envelope": env,
        "hvac": {
            "cop_mode": "constant",
            "cop_value": 3.0,
            "heat_mode": "heat_pump",
            "cop_heat": 3.0,
            "P_rated_w": 2500.0,
            "P_rated_heat_w": 2500.0,
            "shr_rh_guard": 100.0,
            "min_on_s": 0.0,
            "min_off_s": 0.0,
            "fan_power_w": 0.0,
        },
        "deh": {"P_ref_w": 300.0, "fan_power_w": 0.0, "control": "on_off"},
        "led": {
            "auto_deduce": False,
            "power_w": 0.0,
            "photoperiod_hours": 24.0,
            "light_start_hour": 0,
        },
        "transpiration": {"method": "daily", "daily_water_L": 2.0},
        "setpoints": {"T_light": 22.0, "T_dark": 20.0, "RH": 70.0},
        "equipment_power_w": 0.0,
        "pv_area_m2": 0.0,
        "battery_kwh": 0.0,
        "site": {"lat": 45.0, "lon": 127.0, "tz_hours": 8.0},
    }
    return DesignProject.from_dict(d)


# ── 1. default off = zero drift ────────────────────────────────────────────


class TestUpgradesOffZeroDrift:
    def test_engine_default_path_sha256_unchanged(self):
        """preset_609 48 h default run: the shared test_23..28 oracle holds
        (W3-E is invisible on the default path) and no erv key appears."""
        from vfed.design.presets import preset_609

        engine = DesignEngine(cache_dir=None)
        result = engine.run(preset_609(), weather=synthetic_weather(48))
        ts_json = json.dumps(result.timeseries, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(ts_json.encode("utf-8")).hexdigest()
        assert digest == ZERO_DRIFT_SHA256
        assert "erv" not in result.summary  # test_11 exact-set pin intact

    def test_explicit_off_bitwise_matches_implicit_default(self):
        """Explicitly-set erv_enabled: false / flow 0 / effs is
        bitwise-identical to the implicit default (no hidden coupling), on
        a project whose HVAC actually heats."""
        engine = DesignEngine(cache_dir=None)
        wx = cold_weather(n=48, t_ext=2.0)
        r_default = engine.run(probe_project(), weather=wx)
        r_off = engine.run(
            probe_project(
                erv_enabled=False,
                erv_flow_m3h=0.0,
                erv_sensible_eff=0.7,
                erv_latent_eff=0.0,
            ),
            weather=wx,
        )
        assert r_default.summary == r_off.summary
        for key in ("load_kw", "E_hvac_Wh", "E_deh_Wh", "T_z", "RH_z"):
            assert r_default.timeseries[key] == r_off.timeseries[key]


# ── 2. fixed-effectiveness physics ─────────────────────────────────────────


class TestERVFormula:
    def test_sensible_net_and_recovered_arithmetic(self):
        """eps_s=0.7, flow 500 m3/h, dT=13 K: m_v=1/6 kg/s, full sensible
        2177.5 W -> net 653.25 W, recovered 1524.25 W (net + recovered =
        full load, the conservation identity of the split)."""
        env = erv_env()  # eps_l = 0 -> latent channel inert
        q_net, m_lat, q_lat, q_rec_s, q_rec_l = env.mechanical_ventilation(
            35.0, 22.0, 0.020, 0.012
        )
        m_v = 500.0 * 1.2 / 3600.0
        q_full = m_v * 1005.0 * 13.0
        assert q_net == pytest.approx(0.3 * q_full, rel=1e-12)
        assert q_net == pytest.approx(653.25, abs=0.01)
        assert q_rec_s == pytest.approx(0.7 * q_full, rel=1e-12)
        assert q_rec_s == pytest.approx(1524.25, abs=0.01)
        assert q_net + q_rec_s == pytest.approx(q_full, rel=1e-12)
        assert m_lat == pytest.approx(m_v * 0.008, rel=1e-12)  # eps_l=0: full dW
        assert q_lat == pytest.approx(m_lat * latent_heat_vaporization(22.0) * 1000.0)
        assert q_rec_l == 0.0

    def test_latent_attenuation_by_enthalpy_core(self):
        """eps_l=0.65: the AH difference entering the room is the
        (1-eps_l)=0.35 share; recovered latent moisture/energy carry 0.65."""
        env = erv_env(erv_latent_eff=0.65)
        q_net, m_lat, q_lat, q_rec_s, q_rec_l = env.mechanical_ventilation(
            30.0, 22.0, 0.020, 0.012
        )
        m_v = 500.0 * 1.2 / 3600.0
        dW = 0.008
        L_v = latent_heat_vaporization(22.0) * 1000.0
        assert m_lat == pytest.approx(0.35 * m_v * dW, rel=1e-12)
        assert q_lat == pytest.approx(0.35 * m_v * dW * L_v, rel=1e-12)
        assert q_rec_l == pytest.approx(0.65 * m_v * dW * L_v, rel=1e-12)

    def test_zero_effectiveness_equals_infiltration(self):
        """eps_s=eps_l=0 reduces EXACTLY to the infiltration expression at
        equal mass flow (ach*V_room == flow): the ERV channel is the same
        mass-flow physics, minus whatever the core recovers."""
        erv = erv_env(erv_sensible_eff=0.0, erv_latent_eff=0.0)
        infil = Envelope(ach=1.0, V_room=500.0)  # 1.0*500/3600 == 500/3600 kg/s
        T_e, T_z, W_e, W_z = 35.0, 22.0, 0.020, 0.012
        q1, m1, ql1, _, _ = erv.mechanical_ventilation(T_e, T_z, W_e, W_z)
        q2, m2, ql2 = infil.infiltration(T_e, T_z, W_e, W_z)
        assert (q1, m1, ql1) == (q2, m2, ql2)  # exact float identity

    def test_recovered_signs_and_disabled_zeros(self):
        """Winter sign convention: T_ext < T_z -> net sensible negative
        (room still loses, less), recovered negative (heat retained); the
        disabled channel returns all zeros."""
        env = erv_env()
        q_net, _, _, q_rec_s, _ = env.mechanical_ventilation(-7.0, 22.0, 0.002, 0.010)
        assert q_net < 0.0 and q_rec_s < 0.0  # heat retained, load reduced
        off = Envelope()  # default: disabled
        assert off.mechanical_ventilation(35.0, 22.0, 0.02, 0.012) == (0, 0, 0, 0, 0)


# ── 3. engine direction probes ─────────────────────────────────────────────


class TestEngineDirection:
    def test_winter_sensible_recovery_saves_heating(self):
        """T_ext=-7 probe, flow 120 m3/h (2 room volumes/h): eps_s 0.7 vs
        0.0 at the same flow -- recovery retains ~1.9 kW of the ~2.9 kW
        fresh-air loss, so mean T_z rises and HVAC electricity falls."""
        engine = DesignEngine(cache_dir=None)
        wx = cold_weather()
        r0 = engine.run(
            probe_project(
                erv_enabled=True, erv_flow_m3h=120.0, erv_sensible_eff=0.0
            ),
            weather=wx,
        )
        r1 = engine.run(
            probe_project(
                erv_enabled=True, erv_flow_m3h=120.0, erv_sensible_eff=0.7
            ),
            weather=wx,
        )
        tz0 = float(np.mean(r0.timeseries["T_z"]))
        tz1 = float(np.mean(r1.timeseries["T_z"]))
        e0 = float(np.sum(r0.timeseries["E_hvac_Wh"]))
        e1 = float(np.sum(r1.timeseries["E_hvac_Wh"]))
        assert tz1 > tz0  # warmer room with heat retained
        assert e1 < e0  # less heat-pump electricity
        assert tz1 > 15.0 and np.isfinite(tz1)  # physically healthy
        s = r1.summary["erv"]
        assert s["annual_recovered_sensible_kwh"] > 0.0
        assert s["annual_recovered_latent_kwh"] == 0.0  # HRV: no latent meter

    def test_latent_recovery_dries_humid_room(self):
        """T_ext=30/85% RH probe, flow 120 m3/h, eps_s fixed 0.7: eps_l
        0.65 vs 0.0 -- the enthalpy core blocks most of the fresh-air
        moisture, so room RH falls and DEH electricity falls."""
        engine = DesignEngine(cache_dir=None)
        wx = hot_humid_weather()
        kw = dict(erv_enabled=True, erv_flow_m3h=120.0, erv_sensible_eff=0.7)
        r0 = engine.run(probe_project(**dict(kw, erv_latent_eff=0.0)), weather=wx)
        r1 = engine.run(probe_project(**dict(kw, erv_latent_eff=0.65)), weather=wx)
        rh0 = float(np.mean(r0.timeseries["RH_z"]))
        rh1 = float(np.mean(r1.timeseries["RH_z"]))
        d0 = float(np.sum(r0.timeseries["E_deh_Wh"]))
        d1 = float(np.sum(r1.timeseries["E_deh_Wh"]))
        assert rh1 < rh0
        assert d1 <= d0
        assert r1.summary["erv"]["annual_recovered_latent_kwh"] > 0.0

    def test_engine_smoke_609_erv_on_is_healthy(self):
        """48 h 609-shaped smoke with ERV on (flow 500, eps_s 0.7, eps_l
        0.65): finite states, RH in bounds, summary self-evidence block
        with the full key set, recovered meters positive."""
        from vfed.design.presets import preset_609

        p = preset_609()
        p.envelope.erv_enabled = True
        p.envelope.erv_flow_m3h = 500.0
        p.envelope.erv_latent_eff = 0.65
        r = DesignEngine(cache_dir=None).run(p, weather=synthetic_weather(48))
        tz = np.asarray(r.timeseries["T_z"], dtype=float)
        rh = np.asarray(r.timeseries["RH_z"], dtype=float)
        assert np.isfinite(tz).all() and np.isfinite(rh).all()
        assert (rh > 0.0).all() and (rh <= 100.0).all()
        assert set(r.summary["erv"]) == {
            "flow_m3h",
            "sensible_eff",
            "latent_eff",
            "annual_recovered_sensible_kwh",
            "annual_recovered_latent_kwh",
        }
        assert r.summary["erv"]["annual_recovered_sensible_kwh"] > 0.0
        assert r.summary["erv"]["annual_recovered_latent_kwh"] > 0.0
        assert r.summary["erv"]["flow_m3h"] == 500.0


# ── 4. contract fail-fast (project.from_dict + Envelope, defence in depth) ─


class TestContractFailFast:
    _site = {"lat": 31.23, "lon": 121.47}

    def test_defaults_and_valid_values_accepted(self):
        p = DesignProject.from_dict({"name": "p", "site": self._site})
        assert p.envelope.erv_enabled is False
        assert p.envelope.erv_flow_m3h == 0.0
        assert p.envelope.erv_sensible_eff == 0.7
        assert p.envelope.erv_latent_eff == 0.0
        q = DesignProject.from_dict(
            {
                "name": "q",
                "site": self._site,
                "envelope": {
                    "erv_enabled": True,
                    "erv_flow_m3h": 500.0,
                    "erv_sensible_eff": 0.85,
                    "erv_latent_eff": 0.65,
                },
            }
        )
        assert q.envelope.erv_enabled is True
        assert q.envelope.erv_flow_m3h == 500.0

    def test_enabled_without_flow_rejected(self):
        with pytest.raises(ValueError, match="requires erv_flow_m3h > 0"):
            DesignProject.from_dict(
                {"name": "bad", "site": self._site,
                 "envelope": {"erv_enabled": True}}
            )

    def test_flow_without_enabled_rejected(self):
        with pytest.raises(ValueError, match="requires"):
            DesignProject.from_dict(
                {"name": "bad", "site": self._site,
                 "envelope": {"erv_flow_m3h": 500.0}}
            )

    @pytest.mark.parametrize("bad", [1.2, -0.1, 0.96])
    def test_sensible_eff_out_of_band_rejected(self, bad):
        with pytest.raises(ValueError, match=r"erv_sensible_eff.*\[0, 0\.95\]"):
            DesignProject.from_dict(
                {"name": "bad", "site": self._site,
                 "envelope": {"erv_enabled": True, "erv_flow_m3h": 500.0,
                              "erv_sensible_eff": bad}}
            )

    @pytest.mark.parametrize("bad", [1.0, -0.05, 0.99])
    def test_latent_eff_out_of_band_rejected(self, bad):
        with pytest.raises(ValueError, match=r"erv_latent_eff.*\[0, 0\.95\]"):
            DesignProject.from_dict(
                {"name": "bad", "site": self._site,
                 "envelope": {"erv_enabled": True, "erv_flow_m3h": 500.0,
                              "erv_latent_eff": bad}}
            )

    @pytest.mark.parametrize("bad", ["true", 1, 0, 1.0, [True]])
    def test_non_bool_enabled_rejected(self, bad):
        with pytest.raises(ValueError, match="erv_enabled must be a boolean"):
            DesignProject.from_dict(
                {"name": "bad", "site": self._site,
                 "envelope": {"erv_enabled": bad}}
            )

    @pytest.mark.parametrize("bad", ["500", None, [500]])
    def test_non_numeric_flow_rejected(self, bad):
        if bad is None:
            return
        with pytest.raises(ValueError, match="erv_flow_m3h must be a number"):
            DesignProject.from_dict(
                {"name": "bad", "site": self._site,
                 "envelope": {"erv_flow_m3h": bad}}
            )

    def test_negative_flow_rejected(self):
        with pytest.raises(ValueError, match=">= 0"):
            DesignProject.from_dict(
                {"name": "bad", "site": self._site,
                 "envelope": {"erv_enabled": True, "erv_flow_m3h": -10.0}}
            )

    def test_device_level_guards_mirror_project(self):
        """The Envelope constructor enforces the same rules (catches
        programmatic constructions that bypass from_dict)."""
        with pytest.raises(ValueError, match="erv_enabled=true requires"):
            Envelope(erv_enabled=True, erv_flow_m3h=0.0)
        with pytest.raises(ValueError, match="silently ignored"):
            Envelope(erv_enabled=False, erv_flow_m3h=10.0)
        with pytest.raises(ValueError, match=r"\[0, 0\.95\]"):
            Envelope(erv_enabled=True, erv_flow_m3h=500.0, erv_sensible_eff=0.96)
        # boundary 0.95 is a valid certified-core ceiling
        env = Envelope(
            erv_enabled=True, erv_flow_m3h=500.0,
            erv_sensible_eff=0.95, erv_latent_eff=0.95,
        )
        assert env.erv_enabled and env.erv_flow_m3h == 500.0
