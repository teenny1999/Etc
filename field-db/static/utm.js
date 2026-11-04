// แปลงพิกัด WGS84 Lat/Long <-> UTM (ไทยใช้โซน 47N และ 48N)
(function (global) {
  const a = 6378137, f = 1 / 298.257223563, k0 = 0.9996;
  const e2 = f * (2 - f), ep2 = e2 / (1 - e2);
  const rad = Math.PI / 180;

  function zoneOf(lng) { return Math.floor((lng + 180) / 6) + 1; }

  function toUTM(lat, lng, forceZone) {
    const zone = forceZone || zoneOf(lng);
    const lon0 = ((zone - 1) * 6 - 180 + 3) * rad;
    const p = lat * rad, l = lng * rad;
    const sinp = Math.sin(p), cosp = Math.cos(p), tanp = Math.tan(p);
    const N = a / Math.sqrt(1 - e2 * sinp * sinp);
    const T = tanp * tanp, C = ep2 * cosp * cosp, A = cosp * (l - lon0);
    const M = a * ((1 - e2 / 4 - 3 * e2 ** 2 / 64 - 5 * e2 ** 3 / 256) * p
      - (3 * e2 / 8 + 3 * e2 ** 2 / 32 + 45 * e2 ** 3 / 1024) * Math.sin(2 * p)
      + (15 * e2 ** 2 / 256 + 45 * e2 ** 3 / 1024) * Math.sin(4 * p)
      - (35 * e2 ** 3 / 3072) * Math.sin(6 * p));
    const E = k0 * N * (A + (1 - T + C) * A ** 3 / 6 + (5 - 18 * T + T * T + 72 * C - 58 * ep2) * A ** 5 / 120) + 500000;
    let Nn = k0 * (M + N * tanp * (A * A / 2 + (5 - T + 9 * C + 4 * C * C) * A ** 4 / 24
      + (61 - 58 * T + T * T + 600 * C - 330 * ep2) * A ** 6 / 720));
    if (lat < 0) Nn += 10000000;
    return { zone, E, N: Nn, south: lat < 0 };
  }

  function fromUTM(zone, E, N, south) {
    const x = E - 500000, y = south ? N - 10000000 : N;
    const lon0 = ((zone - 1) * 6 - 180 + 3) * rad;
    const mu = (y / k0) / (a * (1 - e2 / 4 - 3 * e2 ** 2 / 64 - 5 * e2 ** 3 / 256));
    const e1 = (1 - Math.sqrt(1 - e2)) / (1 + Math.sqrt(1 - e2));
    const p1 = mu + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * Math.sin(2 * mu)
      + (21 * e1 ** 2 / 16 - 55 * e1 ** 4 / 32) * Math.sin(4 * mu)
      + (151 * e1 ** 3 / 96) * Math.sin(6 * mu) + (1097 * e1 ** 4 / 512) * Math.sin(8 * mu);
    const sin1 = Math.sin(p1), cos1 = Math.cos(p1), tan1 = Math.tan(p1);
    const N1 = a / Math.sqrt(1 - e2 * sin1 * sin1);
    const T1 = tan1 * tan1, C1 = ep2 * cos1 * cos1;
    const R1 = a * (1 - e2) / Math.pow(1 - e2 * sin1 * sin1, 1.5);
    const D = x / (N1 * k0);
    const lat = p1 - (N1 * tan1 / R1) * (D * D / 2 - (5 + 3 * T1 + 10 * C1 - 4 * C1 * C1 - 9 * ep2) * D ** 4 / 24
      + (61 + 90 * T1 + 298 * C1 + 45 * T1 * T1 - 252 * ep2 - 3 * C1 * C1) * D ** 6 / 720);
    const lng = lon0 + (D - (1 + 2 * T1 + C1) * D ** 3 / 6
      + (5 - 2 * C1 + 28 * T1 - 3 * C1 * C1 + 8 * ep2 + 24 * T1 * T1) * D ** 5 / 120) / cos1;
    return { lat: lat / rad, lng: lng / rad };
  }

  global.UTM = { toUTM, fromUTM, zoneOf };
})(window);
