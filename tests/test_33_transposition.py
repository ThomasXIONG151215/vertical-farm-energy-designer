"""G2 (Wave 1): POA transposition — configurable albedo + Hay-Davies sky.

Covers the weather_bridge side of G2 (Agent B):

* default parameters (``albedo=0.2``, ``transposition="isotropic"``)
  reproduce the pre-G2 transposition bit-for-bit (complement of the
  golden gate, test_31), for both the Erbs-split path (GHI-only input)
  and the horizontal-components path (Open-Meteo convention);
* albedo enters ONLY through the ground-reflection term
  ``albedo * GHI * (1 - cos t)/2``: monotone non-decreasing POA, exactly
  linear in albedo, exactly zero at albedo=0 (both sky models), and the
  vertical facade (tilt 90) gains more per albedo step than tilt 20;
* ``hay_davies`` (Hay & Davies 1980) stays inside a physically sensible
  envelope under clear skies and reduces to the isotropic model under
  overcast (AI -> 0);
* invalid model names / out-of-band albedo fail fast with pure-ASCII
  messages (add_poa AND fetch_weather, before any network I/O);
* the cache key keeps the pre-G2 filename byte-for-byte for default
  parameters and only tags NON-default parameterisations (string-level
  assertions on ``_cache_path`` — no cache files are written, no
  network is touched by this module).

Formula references (see add_poa docstring): Duffie & Beckman, "Solar
Engineering of Thermal Processes", 4th ed., eq. 1.4.1 (extraterrestrial
normal irradiance, solar constant 1361 W/m^2 per the TSI reference value,
Gueymard 2018 / ISO 21348) and eq. 2.16.7 (Hay-Davies transposed sky
diffuse: DHI * [(1 - AI) * (1 + cos t)/2 + AI * Rb], AI = DNI/D_on,
Rb = cos(incidence)/cos(zenith)).
"""

import numpy as np
import pandas as pd
import pytest

from vfed.weather.weather_bridge import (
    TRANSPOSITION_MODELS,
    _cache_path,
    _solar_geometry,
    add_poa,
    erbs_split,
    fetch_weather,
)

# Shanghai site defaults (same constants as the module defaults).
LAT, LON, TZ = 31.2, 121.5, 8.0


# ---------------------------------------------------------------------------
# Synthetic weather builders (deterministic, no network)
# ---------------------------------------------------------------------------


def _hourly_index(days, start):
    idx = pd.date_range(start=start, periods=days * 24, freq="h")
    idx.name = "timestamp"
    return idx


def _sin_altitude(idx):
    zen, _ = _solar_geometry(LAT, LON, TZ, idx)
    return np.sin(np.deg2rad(90.0 - zen))


def _clear_sky_df(days=4, start="2025-06-10"):
    """Clear-sky-like GHI (W/m^2): ~950 W/m^2 peak, 0 at night."""
    idx = _hourly_index(days, start)
    sin_alt = np.maximum(_sin_altitude(idx), 0.0)
    return pd.DataFrame({"shortwave_radiation": 950.0 * sin_alt ** 1.2}, index=idx)


def _overcast_df(days=2, start="2025-06-12"):
    """Overcast GHI (W/m^2): ~80 W/m^2 peak, horizon-tapered so the Erbs
    split never sees a flat-60 horizon spike (which would inflate DNI
    artificially at sunrise/sunset)."""
    idx = _hourly_index(days, start)
    sin_alt = np.maximum(_sin_altitude(idx), 0.0)
    return pd.DataFrame({"shortwave_radiation": 80.0 * sin_alt}, index=idx)


def _legacy_poa_reference(df, tilt, azimuth, albedo=0.2):
    """In-test re-implementation of the PRE-G2 add_poa arithmetic (the
    formula frozen at weather_bridge.py add_poa before Wave 1 G2), operand
    order verbatim, for the Erbs-split (GHI-only) input path.

    Returns (beam_poa, diffuse_poa, ground, poa) exactly as the legacy
    code computed them, so equality is bitwise, not approximate.
    """
    ghi = df["shortwave_radiation"].values.astype(float)
    zen, sol_az = _solar_geometry(LAT, LON, TZ, df.index)
    diffuse_h, dni = erbs_split(ghi, zen)
    zen_r, sol_az_r = np.deg2rad(zen), np.deg2rad(sol_az)
    tilt_r, surf_az_r = np.deg2rad(tilt), np.deg2rad(azimuth)
    cos_inc = np.sin(zen_r) * np.cos(surf_az_r - sol_az_r) * np.sin(tilt_r) + np.cos(
        zen_r
    ) * np.cos(tilt_r)
    cos_inc = np.clip(cos_inc, 0.0, None)
    beam_poa = dni * cos_inc
    diffuse_poa = diffuse_h * (1 + np.cos(tilt_r)) / 2.0
    alb = albedo
    ground = alb * ghi * (1 - np.cos(tilt_r)) / 2.0
    poa = np.clip(beam_poa + diffuse_poa + ground, 0.0, None)
    return beam_poa, diffuse_poa, ground, poa


# ---------------------------------------------------------------------------
# 1. Default parameters are bit-identical to the pre-G2 model
# ---------------------------------------------------------------------------


class TestDefaultPathBitwise:
    def test_erbs_path_matches_pre_g2_formula(self):
        # Non-default geometry (tilt 25 / azimuth 195) proves the identity
        # is not an accident of the default angles.
        df = _clear_sky_df()
        res = add_poa(df, tilt=25.0, azimuth=195.0, lat=LAT, lon=LON, tz_hours=TZ)
        beam, diff, ground, poa = _legacy_poa_reference(df, 25.0, 195.0)
        assert np.array_equal(res["poa_radiation"].to_numpy(), poa)
        assert np.array_equal(res["direct_radiation"].to_numpy(), beam)
        assert np.array_equal(res["diffuse_radiation"].to_numpy(), diff + ground)

    def test_horizontal_components_path_matches_pre_g2_formula(self):
        # Input carries Open-Meteo-style horizontal direct/diffuse columns:
        # DNI is recovered as direct / max(cos(zenith), 1e-3).
        df = _clear_sky_df()
        zen, _ = _solar_geometry(LAT, LON, TZ, df.index)
        ghi = df["shortwave_radiation"].to_numpy()
        dhi, dni = erbs_split(ghi, zen)
        cos_z = np.clip(np.cos(np.deg2rad(zen)), 1e-3, 1.0)
        comp = df.copy()
        comp["direct_radiation"] = dni * cos_z
        comp["diffuse_radiation"] = dhi
        res = add_poa(comp, tilt=20.0, azimuth=180.0, lat=LAT, lon=LON, tz_hours=TZ)

        dni_ref = comp["direct_radiation"].values.astype(float) / np.maximum(
            np.cos(np.deg2rad(zen)), 1e-3
        )
        diffuse_h_ref = comp["diffuse_radiation"].values.astype(float)
        zen_r, sol_az_r = np.deg2rad(zen), np.deg2rad(
            _solar_geometry(LAT, LON, TZ, df.index)[1]
        )
        tilt_r, surf_az_r = np.deg2rad(20.0), np.deg2rad(180.0)
        cos_inc = np.clip(
            np.sin(zen_r) * np.cos(surf_az_r - sol_az_r) * np.sin(tilt_r)
            + np.cos(zen_r) * np.cos(tilt_r),
            0.0,
            None,
        )
        beam = dni_ref * cos_inc
        diffuse = diffuse_h_ref * (1 + np.cos(tilt_r)) / 2.0
        ground = 0.2 * ghi * (1 - np.cos(tilt_r)) / 2.0
        poa = np.clip(beam + diffuse + ground, 0.0, None)
        assert np.array_equal(res["poa_radiation"].to_numpy(), poa)
        assert np.array_equal(res["direct_radiation"].to_numpy(), beam)
        assert np.array_equal(res["diffuse_radiation"].to_numpy(), diffuse + ground)

    def test_explicit_default_args_equal_default_call_bitwise(self):
        df = _clear_sky_df()
        implicit = add_poa(df, tilt=30.0, azimuth=170.0, lat=LAT, lon=LON, tz_hours=TZ)
        explicit = add_poa(
            df,
            tilt=30.0,
            azimuth=170.0,
            lat=LAT,
            lon=LON,
            tz_hours=TZ,
            albedo=0.2,
            transposition="isotropic",
        )
        assert np.array_equal(
            implicit["poa_radiation"].to_numpy(), explicit["poa_radiation"].to_numpy()
        )
        assert np.array_equal(
            implicit["diffuse_radiation"].to_numpy(),
            explicit["diffuse_radiation"].to_numpy(),
        )


# ---------------------------------------------------------------------------
# 2. albedo enters only through the ground-reflection term
# ---------------------------------------------------------------------------


class TestAlbedoGroundTerm:
    @pytest.mark.parametrize("transposition", TRANSPOSITION_MODELS)
    @pytest.mark.parametrize("tilt", [20.0, 90.0])
    def test_poa_monotone_nondecreasing_in_albedo(self, tilt, transposition):
        df = _clear_sky_df()
        poas = [
            add_poa(
                df, tilt=tilt, azimuth=180.0, albedo=a, transposition=transposition
            )["poa_radiation"].to_numpy()
            for a in (0.1, 0.3, 0.5)
        ]
        assert np.all(poas[1] >= poas[0])
        assert np.all(poas[2] >= poas[1])

    def test_vertical_facade_gain_exceeds_tilt20_gain(self):
        # The ground-reflection view factor (1 - cos t)/2 is 0.5 at the
        # vertical facade vs ~0.03 at tilt 20, so the same albedo step must
        # add more energy to the facade.
        df = _clear_sky_df()
        ghi_sum = df["shortwave_radiation"].sum()
        gains = {}
        for tilt in (20.0, 90.0):
            lo = add_poa(df, tilt=tilt, azimuth=180.0, albedo=0.1)["poa_radiation"].sum()
            hi = add_poa(df, tilt=tilt, azimuth=180.0, albedo=0.5)["poa_radiation"].sum()
            gains[tilt] = hi - lo
        assert gains[90.0] > gains[20.0]
        # and both gains are the analytic ground term (within float noise)
        for tilt, gain in gains.items():
            expected = (
                0.4 * ghi_sum * (1 - np.cos(np.deg2rad(tilt))) / 2.0
            )
            assert gain == pytest.approx(expected, rel=1e-9, abs=1e-6)

    @pytest.mark.parametrize("transposition", TRANSPOSITION_MODELS)
    @pytest.mark.parametrize("tilt", [20.0, 90.0])
    def test_ground_term_exactly_linear_in_albedo(self, tilt, transposition):
        df = _clear_sky_df()
        ghi = df["shortwave_radiation"].to_numpy()
        lo = add_poa(
            df, tilt=tilt, azimuth=180.0, albedo=0.1, transposition=transposition
        )["poa_radiation"].to_numpy()
        hi = add_poa(
            df, tilt=tilt, azimuth=180.0, albedo=0.5, transposition=transposition
        )["poa_radiation"].to_numpy()
        expected_delta = 0.4 * ghi * (1 - np.cos(np.deg2rad(tilt))) / 2.0
        assert np.allclose(hi - lo, expected_delta, rtol=1e-9, atol=1e-9)

    @pytest.mark.parametrize("transposition", TRANSPOSITION_MODELS)
    def test_albedo_zero_ground_term_exactly_zero(self, transposition):
        # With albedo=0 the ground term must vanish BITWISE (the legacy
        # expression evaluated with 0.0), not merely be small.
        df = _clear_sky_df()
        res = add_poa(df, tilt=20.0, azimuth=180.0, albedo=0.0, transposition=transposition)
        beam = res["direct_radiation"].to_numpy()
        tilt_r = np.deg2rad(20.0)
        ghi = df["shortwave_radiation"].to_numpy()

        zen, sol_az = _solar_geometry(LAT, LON, TZ, df.index)
        zen_r, sol_az_r = np.deg2rad(zen), np.deg2rad(sol_az)
        diffuse_h, dni = erbs_split(ghi, zen)
        cos_inc = np.clip(
            np.sin(zen_r) * np.cos(np.deg2rad(180.0) - sol_az_r) * np.sin(tilt_r)
            + np.cos(zen_r) * np.cos(tilt_r),
            0.0,
            None,
        )
        iso_view = (1 + np.cos(tilt_r)) / 2.0
        if transposition == "hay_davies":
            cos_z = np.clip(np.cos(zen_r), 1e-3, 1.0)
            d_on = 1361.0 * (
                1.0 + 0.033 * np.cos(np.deg2rad(360.0 * df.index.dayofyear.values / 365.0))
            )
            ai = np.clip(dni / d_on, 0.0, 1.0)
            diffuse_poa = diffuse_h * ((1.0 - ai) * iso_view + ai * (cos_inc / cos_z))
        else:
            diffuse_poa = diffuse_h * iso_view
        # the exact legacy expression with albedo = 0.0 (adds +0.0)
        expected = np.clip(
            beam + diffuse_poa + 0.0 * ghi * (1 - np.cos(tilt_r)) / 2.0, 0.0, None
        )
        assert np.array_equal(res["poa_radiation"].to_numpy(), expected)


# ---------------------------------------------------------------------------
# 3. Hay-Davies: clear-sky envelope + overcast degeneration
# ---------------------------------------------------------------------------


class TestHayDavies:
    @pytest.mark.parametrize("tilt", [20.0, 90.0])
    def test_clear_sky_difference_within_envelope(self, tilt):
        # |POA_HD - POA_iso| stays under 10% of GHI hour by hour (and in
        # daily energy): the circumsolar redistribution moves a bounded
        # share of the diffuse, it must not approach beam magnitudes.
        df = _clear_sky_df()
        ghi = df["shortwave_radiation"].to_numpy()
        iso = add_poa(df, tilt=tilt, azimuth=180.0)["poa_radiation"].to_numpy()
        hd = add_poa(df, tilt=tilt, azimuth=180.0, transposition="hay_davies")[
            "poa_radiation"
        ].to_numpy()
        day = ghi >= 20.0
        assert day.any()
        assert np.all(np.abs(hd[day] - iso[day]) <= 0.10 * ghi[day] + 1e-9)
        assert (
            np.abs(hd[day] - iso[day]).sum() <= 0.10 * ghi[day].sum() + 1e-6
        )

    def test_clear_sky_actually_differs_from_isotropic(self):
        # Guard against a degenerate hay_davies == isotropic shortcut.
        df = _clear_sky_df()
        iso = add_poa(df, tilt=20.0)["poa_radiation"].to_numpy()
        hd = add_poa(df, tilt=20.0, transposition="hay_davies")["poa_radiation"].to_numpy()
        assert np.abs(hd - iso).max() > 1.0  # W/m^2, calibrated ~10.4

    def test_overcast_reduces_to_isotropic(self):
        # DNI ~ 0 -> AI ~ 0 -> Hay-Davies degenerates to the isotropic sky.
        df = _overcast_df()
        iso = add_poa(df, tilt=20.0, azimuth=180.0)["poa_radiation"].to_numpy()
        hd = add_poa(df, tilt=20.0, azimuth=180.0, transposition="hay_davies")[
            "poa_radiation"
        ].to_numpy()
        assert np.allclose(hd, iso, rtol=0.0, atol=0.05)

    @pytest.mark.parametrize("transposition", TRANSPOSITION_MODELS)
    def test_poa_components_sum_to_poa(self, transposition):
        # direct + diffuse (as stored) must reproduce poa (module contract,
        # weather docstring: "those two columns sum to the plane-of-array
        # irradiance").  Not bitwise: internally poa is assembled as
        # (beam + diffuse) + ground while the stored columns sum as
        # beam + (diffuse + ground) — associativity-level float noise only.
        df = _clear_sky_df()
        res = add_poa(df, tilt=20.0, azimuth=180.0, transposition=transposition)
        assert np.allclose(
            res["direct_radiation"].to_numpy() + res["diffuse_radiation"].to_numpy(),
            res["poa_radiation"].to_numpy(),
            rtol=1e-12,
            atol=1e-9,
        )


# ---------------------------------------------------------------------------
# 4. Fail-fast validation (pure-ASCII messages)
# ---------------------------------------------------------------------------


class TestValidation:
    def test_add_poa_invalid_transposition_raises_ascii(self):
        df = _clear_sky_df(days=1)
        with pytest.raises(ValueError) as ei:
            add_poa(df, transposition="perez")
        msg = str(ei.value)
        assert "transposition" in msg
        assert msg.isascii()

    @pytest.mark.parametrize("albedo", [-0.1, 1.5])
    def test_add_poa_albedo_out_of_band_raises_ascii(self, albedo):
        df = _clear_sky_df(days=1)
        with pytest.raises(ValueError) as ei:
            add_poa(df, albedo=albedo)
        msg = str(ei.value)
        assert "albedo" in msg
        assert msg.isascii()

    def test_fetch_weather_invalid_transposition_raises_before_any_io(self, tmp_path):
        # Entry-point guard: must fail BEFORE any cache bookkeeping or
        # network access (no requests dependency needed to prove this).
        with pytest.raises(ValueError, match="transposition"):
            fetch_weather(LAT, LON, 2025, cache_dir=tmp_path, transposition="reindl")

    def test_fetch_weather_albedo_out_of_band_raises(self, tmp_path):
        with pytest.raises(ValueError, match="albedo"):
            fetch_weather(LAT, LON, 2025, cache_dir=tmp_path, albedo=2.0)


# ---------------------------------------------------------------------------
# 5. Cache-key backward compatibility (string-level, no files written)
# ---------------------------------------------------------------------------


class TestCacheKeyBackCompat:
    def test_default_key_is_byte_identical_to_pre_g2_name(self, tmp_path):
        # This exact filename exists in weather_cache/ today; keeping the
        # default key byte-identical is what makes old caches keep hitting
        # (no refetch, no network).
        p = _cache_path(tmp_path, 31.2, 121.5, 2025)
        assert p.name == "weather_31.200_121.500_2025_t20.000_a180.000_z8.000.csv"

    def test_explicit_defaults_keep_the_legacy_name(self, tmp_path):
        legacy = _cache_path(tmp_path, 31.2, 121.5, 2025)
        explicit = _cache_path(
            tmp_path, 31.2, 121.5, 2025, albedo=0.2, transposition="isotropic"
        )
        assert explicit == legacy

    def test_power_suffix_unchanged_for_defaults(self, tmp_path):
        p = _cache_path(tmp_path, 31.2, 121.5, 2025, provider="nasa-power")
        assert p.name == "weather_31.200_121.500_2025_t20.000_a180.000_z8.000_power.csv"

    def test_non_default_parameters_get_tagged_key(self, tmp_path):
        legacy = _cache_path(tmp_path, 31.2, 121.5, 2025).name
        both = _cache_path(tmp_path, 31.2, 121.5, 2025, albedo=0.3, transposition="hay_davies")
        assert both.name == (
            "weather_31.200_121.500_2025_t20.000_a180.000_z8.000_r0.300_mhay_davies.csv"
        )
        assert both.name != legacy
        alb_only = _cache_path(tmp_path, 31.2, 121.5, 2025, albedo=0.3)
        assert alb_only.name != legacy and "_r0.300_misotropic" in alb_only.name
        model_only = _cache_path(tmp_path, 31.2, 121.5, 2025, transposition="hay_davies")
        assert model_only.name != legacy and "_r0.200_mhay_davies" in model_only.name
        # provider tag and transposition tag compose
        combo = _cache_path(
            tmp_path, 31.2, 121.5, 2025, provider="nasa-power", albedo=0.3
        )
        assert combo.name.endswith("_z8.000_power_r0.300_misotropic.csv")
