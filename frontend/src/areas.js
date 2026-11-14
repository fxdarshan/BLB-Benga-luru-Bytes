// Approximate centres of the dataset's 30 Bangalore areas, to find the one nearest a diner.
// They only need to be close enough to tell neighbouring areas apart. The location never leaves
// the browser: nothing here calls a server.

export const AREA_CENTRES = {
  BTM: [12.9166, 77.6101],
  Banashankari: [12.9255, 77.5468],
  "Bannerghatta Road": [12.888, 77.597],
  Basavanagudi: [12.9406, 77.5738],
  Bellandur: [12.9304, 77.6784],
  "Brigade Road": [12.9716, 77.607],
  Brookefield: [12.9655, 77.7185],
  "Church Street": [12.975, 77.603],
  "Electronic City": [12.8452, 77.6602],
  "Frazer Town": [12.9967, 77.6141],
  HSR: [12.9116, 77.6474],
  Indiranagar: [12.9784, 77.6408],
  "JP Nagar": [12.9063, 77.5857],
  Jayanagar: [12.925, 77.5938],
  "Kalyan Nagar": [13.028, 77.64],
  Kammanahalli: [13.0159, 77.6379],
  "Koramangala 4th Block": [12.9327, 77.6299],
  "Koramangala 5th Block": [12.9346, 77.619],
  "Koramangala 6th Block": [12.939, 77.624],
  "Koramangala 7th Block": [12.9366, 77.6136],
  "Lavelle Road": [12.9696, 77.5967],
  "MG Road": [12.9757, 77.6061],
  Malleshwaram: [13.0035, 77.571],
  Marathahalli: [12.9569, 77.7011],
  "New BEL Road": [13.03, 77.568],
  "Old Airport Road": [12.961, 77.658],
  Rajajinagar: [12.991, 77.5525],
  "Residency Road": [12.968, 77.608],
  "Sarjapur Road": [12.91, 77.685],
  Whitefield: [12.9698, 77.75],
};

// Further than this from every area, the diner is taken to be outside Bangalore.
export const MAX_DISTANCE_KM = 25;

/** Great-circle distance between two points, in kilometres. */
export function distanceKm([lat1, lon1], [lat2, lon2]) {
  const rad = Math.PI / 180;
  const a =
    Math.sin(((lat2 - lat1) * rad) / 2) ** 2 +
    Math.cos(lat1 * rad) * Math.cos(lat2 * rad) * Math.sin(((lon2 - lon1) * rad) / 2) ** 2;
  return 2 * 6371 * Math.asin(Math.sqrt(a));
}

/** The nearest of `areas` that has a known centre, with its distance, or null if none is
 *  within MAX_DISTANCE_KM. */
export function nearestArea(point, areas) {
  let best = null;
  for (const area of areas) {
    const centre = AREA_CENTRES[area];
    if (!centre) continue;
    const km = distanceKm(point, centre);
    if (!best || km < best.km) best = { area, km };
  }
  return best && best.km <= MAX_DISTANCE_KM ? best : null;
}
