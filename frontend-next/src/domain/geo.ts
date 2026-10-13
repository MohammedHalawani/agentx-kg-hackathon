/**
 * Approximate city-centre coordinates for Saudi cities (public geography, not operational
 * data). Used only to place city labels and frame maps; evidence positions always come
 * from the records themselves.
 */
export const cityLocations: Record<string, [number, number]> = {
  Riyadh: [24.7136, 46.6753],
  Dammam: [26.4207, 50.0888],
  Khobar: [26.2794, 50.2083],
  Jeddah: [21.5433, 39.1728],
  "Al Hofuf": [25.3646, 49.5876],
  Buraydah: [26.3592, 43.9818],
};
/** Additional cities the backend dataset uses. Kept apart so the lab's city list is unchanged. */
export const moreCityLocations: Record<string, [number, number]> = {
  Hofuf: [25.3646, 49.5876],
  Dhahran: [26.2886, 50.114],
  Jubail: [27.0046, 49.646],
  Makkah: [21.3891, 39.8579],
  Madinah: [24.5247, 39.5692],
  Qassim: [26.3592, 43.9818],
  Tabuk: [28.3835, 36.5662],
  Abha: [18.2164, 42.5053],
  Taif: [21.2703, 40.4158],
  Hail: [27.5114, 41.7208],
  Jazan: [16.8892, 42.5511],
  Najran: [17.4933, 44.1277],
  Yanbu: [24.0895, 38.0618],
};
