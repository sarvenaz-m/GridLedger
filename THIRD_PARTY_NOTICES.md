# Third-party data

**ElectricityLoadDiagrams20112014**

- Creator: **Artur Trindade**
- Source: UCI Machine Learning Repository
- DOI: https://doi.org/10.24432/C58C86
- Dataset page: https://archive.ics.uci.edu/dataset/321/electricityloaddiagrams20112014
- License: **Creative Commons Attribution 4.0 International**
- License text: https://creativecommons.org/licenses/by/4.0/

GridLedger's MT_001–MT_020 extract changes the source through client/date selection and averaging four quarter-hour kW readings into hourly power. Provider clock labels remain timezone-naive. Analysis excludes DST transition targets and initial pre-activation zeros using the documented protocol.

`data/uci_hourly.csv`, UCI observations embedded in `assets/real-data.*`, and derived real-data evidence/figures carry this attribution and are distributed under CC BY 4.0. Preserve this notice and attribution when redistributing them. No endorsement by the creator or UCI is implied.

GridLedger code and the original synthetic experiment use the repository's MIT license. Dependencies retain their own licenses.
