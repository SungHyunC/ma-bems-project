# MA-BEMS sample data

## bdg2-fox-campus-2017-07-12.csv

One summer weekday (2017-07-12) of measured hourly electricity (written at 15-min steps, linear within each hour) from four buildings on the
Building Data Genome 2 "Fox" site (a US university campus, US/Mountain time), mapped onto the
Helio Campus buildings and rescaled to their plug/process/IT size:

| column  | BDG2 building          | use                | scaled so the daily max is |
|---------|------------------------|--------------------|----------------------------|
| load_B1 | Fox_office_Gaylord     | office             | 110 kW                     |
| load_B2 | Fox_education_Gloria   | college laboratory | 190 kW                     |
| load_B3 | Fox_lodging_Alana      | dormitory          | 85 kW                      |
| load_B4 | Fox_education_Willis   | college laboratory with the flattest load (data-centre stand-in) | 288 kW |

The shape of each day is measured; the magnitude is not (the dashboard's `load_B*` columns replace
its modelled plug + process + IT load, while HVAC and lighting stay modelled).

In the evaluation (`eval/`, dataset `bdg2`) this one measured day is repeated for every simulated day, so the result is "agents vs. a rule-based BMS on a measured non-HVAC load shape, rescaled to the Helio Campus", not on measured load of the campus. The dashboard's shadow mode reads a meter CSV (timestamp plus building kW, at 15-minute, 30-minute or hourly steps, at least one day). It rescales the file to campus size keeping the shape, prices it at KEPCO summer weekday rates and reports what the agents would have saved.

`price` is the KEPCO tariff 일반용전력(을) 고압A 선택 II, 2026-06-01 edition, summer weekday, in KRW/kWh
(off-peak 87.3 · mid 140.2 · peak 222.3; peak 15-21 h, mid 08-15 and 21-22 h), taken from
`BEMS/backend/tariff.py`, which was checked against the official KEPCO tariff PDFs. VAT, funds,
fuel adjustments and the basic / demand charge (8,320 KRW per kW per month) are not included.

Source: Miller, C. et al. "The Building Data Genome Project 2", Scientific Data 7, 368 (2020),
https://github.com/buds-lab/building-data-genome-project-2. Licence: CC BY-SA 4.0. This derived
file is shared under the same licence.
