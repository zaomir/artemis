# F23 — La Quinta georeferenced locator, not a project site plan

Date: 2026-11-05. Status: FACT-CHECKED POINT INPUTS, diagram draft; no construction/land entitlement claimed.

## Evidence

1. **La Quinta, Santa Úrsula**: municipal site calls La Quinta a residential area *below TF-5*, between Camino del Mar and the lower Calvario area. Source: https://www.santaursula.es/descubre-santa-ursula/barrios/
2. **La Quinta neighbourhood marker**: OpenStreetMap node 554792546, coordinates 28.43187, -16.49517 (as mirrored by Mapcarta: https://mapcarta.com/N554792546 ). This is an indicative neighbourhood POI, **not the project's plot**.
3. **Puerto de la Cruz**: AEMET municipality central coordinates 28.41552846, -16.55000025. Source: https://www.aemet.es/en/eltiempo/prediccion/municipios/puerto-de-la-cruz-id38028 . (The harbour has different coordinates; do not claim distance to it.)
4. **Bus stop La Quinta TITSA 4004**: official TITSA stop data 28.4271, -16.493, https://titsa.com/ajax/xGetInfoParada.php?id_parada=4004 .
5. **TF-5 exit 29 / Mirador de La Quinta context**: municipal tourist guidance: https://www.santaursula.es/areas/turismo-2/ventana-del-norte-de-tenerife/mirador-de-la-quinta/ . No roads or routes depicted on diagram.

## Display contract

- Plot only verified point coordinates with a simple equirectangular coordinate transform. *No invented topography, roads, coastlines, parcel outline, roads distances, driving times or location-dependent views*.
- Display La Quinta as **neighbourhood centre**, not a marker at a chosen land parcel.
- Render descriptive warning and external OSM neighbourhood map link in each locale.
- Do not generate an imaginary map using a text-to-image model.
- Keep DOM/SVG points keyboard accessible through equivalent text and accessible alt/caption. Do not include identifiable people.
- External OSM: https://www.openstreetmap.org/?mlat=28.43187&mlon=-16.49517#map=14/28.43187/-16.49517 .
- OSM attribution: © OpenStreetMap contributors (point source ODbL); optional static image assets must not hotlink a raster tile without license attribution. This custom chart has no copied tiles.

Source of truth: first-party municipal/TITSA/AEMET pages and OSM node. Geographic differences in coordinate accuracy mean this is a **locator diagram**, not a cadastral or topographic survey.
