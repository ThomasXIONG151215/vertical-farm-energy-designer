## modeling aspects to improve

- [] van henten model in G:\VFLab\VFLAB\vertical-farm-energy-designer\reference\van-henten that can connect LED settings and environment and plant growth

- [] need to be able to set parameters of LED: efficacy, PPFD; and automatically deduce resulting power rate

- [] HVAC and DEH should be settings-oriented, meaning it calculates the cooling and dehumidification required for both to maintain the desired T and RH; also, their COP models should come from classical equations and be simple

## Logical workflow

provide simulation in the following phases;

- farm definition; location(city name or coordinates (need a small search engine, check if open-meteo has one)), insulation, volume, sizing, 

- internal energy device parameters ranges and steps; LED, HVAC, DEH

- external energy device parameters range and steps: PV, BES

- operation settings; photoperiod, temperature and humidity settings, transpiration model

- internal load modeling: ODE loop for whole year; suppose T and RH will be absolutely according to the operation; deduce energy consumption and plant growth according to van henten model; use LED, HVAC and DEH and weather load from envelope insulations\

- external load modeling; PV+BES modeling

- output energy consumption and plant growth; give an estimated kWh/kg with +- 25% range
