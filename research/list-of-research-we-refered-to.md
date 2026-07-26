# List of Research We Referenced

## Hua Bao (包华) — PFAL / Indoor Farming Publications (2023–2026)

### References with Descriptions

#### [1] W. Cai, F. Qi, L. Zha, G. Chen, J. Zhang, M. Song, and H. Bao
**Few-shot and interpretable agentic framework based on large language models for data-efficient plant phenotyping.**  
*Comput. Electron. Agric.*, vol. 243, p. 111382, 2026.  

**Description:** LLM-based plant phenotyping — Few-shot agentic framework using large language models for data-efficient plant phenotype analysis. Relevant to VFED plant growth modeling and phenotyping integration.

#### [2] T. Xiong, W. Cai, Y. Hu, M. Song, T. Qian, and H. Bao
**Photovoltaic-battery integration strategy in plant factories with artificial lighting.**  
*Energy Build.*, vol. 361, p. 117462, 2026.  

**Description:** PV-Battery integration for PFALs — Energy system optimization integrating photovoltaics and battery storage for plant factories with artificial lighting (PFALs). **Directly relevant to VFED's PV-Battery-Grid energy system module.**

#### [3] Z. Yu, Y. Liu, X. Hu, J. Xue, L. Zha, J. Zhang, H. Bao, and D. Lai
**CFD-driven Bayesian optimization of localized ventilation to achieve desired microclimate conditions in plant factories.**  
*Comput. Electron. Agric.*, vol. 240, p. 111225, 2026.  

**Description:** CFD + Bayesian optimization for ventilation — Computational fluid dynamics coupled with Bayesian optimization to optimize localized ventilation for uniform microclimate in plant factories. Relevant to VFED's HVAC and airflow modeling.

#### [4] T. Xiong, G. Chen, W. Cai, L. Zha, G. Xu, A. Wang, Y. Wei, X. Lu, S. Wei, D. Lai, J. Zhang, and H. Bao
**Design and development of a low-cost and energy-efficient container farm for leafy greens.**  
*Cleaner Eng. Technol.*, vol. 30, p. 101135, 2026.  

**Description:** Low-cost container farm design — Engineering design and energy-efficiency optimization of container-based plant factories for leafy greens. **Directly relevant to VFED's container farm presets (preset 609) and energy modeling.**

#### [5] W. Cai, K. Bu, L. Zha, J. Zhang, D. Lai, and H. Bao
**Energy consumption of plant factory with artificial light: Challenges and opportunities.**  
*Renew. Sustain. Energy Rev.*, vol. 210, p. 115235, 2025.  

**Description:** PFAL energy review (2025) — Comprehensive review of energy consumption challenges and opportunities in plant factories with artificial light (PFAL). **Key reference for VFED's energy modeling framework and literature positioning.**

#### [6] W. Cai, S. Li, L. Zha, J. He, J. Zhang, and H. Bao
**Significantly enhanced energy efficiency through reflective materials integration in plant factories with artificial light.**  
*Appl. Energy*, vol. 377, p. 124587, 2025.  

**Description:** Reflective materials for lighting efficiency — Experimental and modeling study showing reflective material integration significantly improves lighting energy efficiency in PFALs. Relevant to VFED's lighting system modeling and energy optimization.

#### [7] Z. Yu, K. Bu, Y. Liu, A. Wang, W. Yuan, J. Xue, J. Zhang, H. Bao, and D. Lai
**Energy examination and optimization workflow for container farms: A case study in Shanghai, China.**  
*Appl. Energy*, vol. 374, p. 124038, 2024.  

**Description:** Container farm energy optimization workflow — End-to-end energy analysis and optimization workflow for container farms with Shanghai case study. **Directly aligns with VFED's design → optimize → evaluate workflow.**

#### [8] K. Bu, Z. Yu, D. Lai, and H. Bao
**Energy-saving effect assessment of various factors in container plant factories: A data-driven random forest approach.**  
*Clean Energy Syst.*, vol. 8, p. 100122, 2024.  

**Description:** Random Forest energy factor assessment — Data-driven ML (Random Forest) to quantify energy-saving contributions of various factors in container plant factories. **Relevant to VFED's sensitivity analysis and factor importance ranking.**

#### [9] L. Jiao, X. Luo, L. Zha, H. Bao, J. Zhang, and X. Gu
**Machine learning assisted water management strategy on a self-sustaining seawater desalination and vegetable cultivation platform.**  
*Comput. Electron. Agric.*, vol. 217, p. 108569, 2024.  

**Description:** ML-assisted water management for integrated desalination+cultivation — Machine learning for water management in a coupled seawater desalination and vegetable cultivation system. Relevant to VFED's water/energy nexus modeling.

#### [10] K. Bu, J. Fan, A. Wang, and H. Bao
**Enhanced dew harvest with porous wind covers.**  
*Sol. Energy Mater. Sol. Cells*, vol. 250, p. 112099, 2023.  

**Description:** Passive dew harvesting with porous covers — Novel porous wind cover design for enhanced dew collection. Relevant to VFED's water recovery and passive cooling strategies in PFALs.

#### [11] K. Bu, Y. Zha, D. Lai, and H. Bao
**Energy Consumption of Plant Factory with Artificial Light: Challenges and Opportunities.**  
*arXiv preprint* arXiv:2405.09643, 2024.  

**Description:** Preprint version of [5] — Early version of the 2025 review paper. Available at arXiv:2405.09643.

---

## Summary by Research Theme

| Theme | Papers | VFED Relevance |
|-------|--------|----------------|
| **Energy System Optimization (PV + Battery + Grid)** | [2] | **Core** — Direct alignment with VFED's `pvbes` module |
| **Container Farm Energy Modeling** | [4], [7], [8] | **Core** — Matches VFED's container farm presets & optimization workflow |
| **PFAL Energy Review & Challenges** | [5], [11] | **Literature positioning** — Defines the problem space VFED addresses |
| **Lighting Efficiency (Reflective Materials)** | [6] | **Lighting module** — Informs LED + reflective surface modeling |
| **HVAC / Ventilation / Microclimate** | [3] | **HVAC module** — CFD-driven optimization aligns with `physics/envelope.py` & `devices/` |
| **Water-Energy Nexus (Desalination, Dew Harvest)** | [9], [10] | **Extended scope** — Water recovery & passive cooling for future VFED versions |
| **ML/AI for Plant Factories** | [1], [8] | **Advanced** — ML factor importance (RF), LLM phenotyping for future ML integration |

---

## Cross-References in VFED Codebase

| VFED Module | Related Papers |
|-------------|----------------|
| `src/pvbes/` (PV-Battery-Grid) | [2] — PV-battery integration strategy |
| `src/design/presets.py` (Preset 609: Container Farm) | [4], [7], [8] — Container farm design, energy workflow, factor assessment |
| `src/design/engine.py` (Optimization workflow) | [7] — Energy examination & optimization workflow |
| `src/physics/engine.py` (ODE solver, envelope) | [3] — CFD ventilation optimization |
| `src/devices/` (LED, HVAC, Dehumidifier) | [6] — Reflective materials for lighting; [3] — Ventilation |
| `src/plants/` (Transpiration, growth) | [1], [9] — Phenotyping, water management |
| `src/design/sweep.py` (Parameter sweep) | [8] — Random Forest factor importance for sensitivity analysis |

---

## Notes

- Papers [1]–[10] retrieved from **Prof. Hua Bao's official publication page**: <https://sites.gc.sjtu.edu.cn/hua-bao/publications> (accessed 2026-07-12).
- Paper [11] is the arXiv preprint of [5]; the peer-reviewed version [5] should be cited preferentially.
- **Core VFED alignment**: Papers [2], [4], [5], [6], [7], [8] directly map to VFED's architecture (energy system, container farm presets, optimization workflow, lighting, HVAC, sensitivity analysis).
- All papers are from **2023–2026**, representing the current state-of-the-art in PFAL energy research.

---

*Last updated: 2026-07-12*  
*Source: Hua Bao (SJTU) publication list + project References.md*