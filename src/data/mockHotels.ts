export interface HotelFeature {
  key: string;
  label: string;
  icon: string;
  value: string;
  detail: string;
  confidence: number;
  source: string;
  evidence?: Record<string, any>;
}

export interface HotelierQuestion {
  id: number;
  feature_key: string;
  question: string;
  answer_raw?: string;
  answer_parsed?: Record<string, any>;
  status: 'pending' | 'answered' | 'disputed';
  asked_at: string;
}

export interface Hotel {
  id: number;
  name: string;
  address: string;
  lat: number;
  lon: number;
  floors: number;
  facade_azimuth: number;
  stars: number;
  price_per_night: number;
  image: string;
  description: string;
  features: HotelFeature[];
  questions: HotelierQuestion[];
  sunset_ray?: { azimuth: number; length_km: number };
  /** Пояснение подбора из API (собирается из evidence собранных характеристик). */
  explanation?: string;
  /** Оценка соответствия запросу, 0..1. */
  score?: number;
}

export interface Route {
  id: number;
  title: string;
  author: string;
  description: string;
  cover_emoji: string;
  hotel_ids: number[];
  key_features: string[];
  days: number;
}

// Mock hotels in Kaliningrad + Zelenogradsk + Curonian Spit area
export const hotels: Hotel[] = [
  {
    id: 1,
    name: "Балтика Зеладринск",
    address: "Зеленоградск, ул. Ленинградская, 12",
    lat: 54.957,
    lon: 20.479,
    floors: 5,
    facade_azimuth: 270,
    stars: 4,
    price_per_night: 5800,
    image: "🏨",
    description: "Современный отель в центре Зеленоградска, в 3 минутах от променада. Фасад обращён на запад — к Балтике.",
    features: [
      { key: "sunset_view", label: "Закат над Балтикой", icon: "🌅", value: "Виден с 3 этажа", detail: "Май–август, азимут 290°. Рельеф и здания не перекрывают линию визирования с 3-го этажа.", confidence: 0.88, source: "SRTM + OSM 3D", evidence: { dem_resolution_m: 30, buildings_in_buffer: 42, azimuth_deg: 290.2, from_floor: 3 } },
      { key: "noise_score", label: "Тишина", icon: "🤫", value: "22/100 (тихо)", detail: "Нет магистралей в радиусе 200м. Ближайший источник шума — residential-улица.", confidence: 0.91, source: "OSM", evidence: { breakdown: { "highway=residential": { count: 2, weight: 2 } } } },
      { key: "walk_to_sea", label: "Пешком до моря", icon: "🚶", value: "4 мин", detail: "420 м по променаду без перехода через трассу. Ровный рельеф.", confidence: 0.93, source: "OSM + DEM", evidence: { distance_m: 420, crosses_highway: false } },
      { key: "night_amenities", label: "Ночная инфраструктура", icon: "🌙", value: "Рестораны до 23:00", detail: "3 ресторана и 1 кафе в радиусе 300м работают до 23:00.", confidence: 0.85, source: "OSM", evidence: { restaurants: 3, cafes: 1, max_closing: "23:00" } },
      { key: "family", label: "Семейный", icon: "👨‍👩‍👧", value: "Да", detail: "Есть детская площадка, кроватки, меню для детей.", confidence: 0.95, source: "hotelier", evidence: { crib: true, playground: true, kids_menu: true } },
      { key: "wikidata_history", label: "Историческое здание", icon: "🏛️", value: "Нет (постр. 2018)", detail: "Здание построено в 2018 году на месте довоенной застройки.", confidence: 0.97, source: "Wikidata", evidence: { year_built: 2018, heritage: false } },
    ],
    questions: [
      { id: 101, feature_key: "pet_friendly", question: "Разрешено ли проживание с домашними животными? Если да, то каких размеров и с какой доплатой?", status: "pending", asked_at: "2026-01-15T10:00:00Z" },
    ],
    sunset_ray: { azimuth: 290, length_km: 10 },
  },
  {
    id: 2,
    name: "Дюны Куршской косы",
    address: "пос. Морское, Куршская коса, 14 км",
    lat: 55.183,
    lon: 20.833,
    floors: 2,
    facade_azimuth: 265,
    stars: 3,
    price_per_night: 4200,
    image: "🏡",
    description: "Уютный гостевой дом на Куршской косе. Прямо у дюн, в окружении соснового леса. Идеально для тех, кто ищет тишину и единение с природой.",
    features: [
      { key: "sunset_view", label: "Закат над Балтикой", icon: "🌅", value: "Виден с 1 этажа", detail: "Прямой вид на дюны и море. Нет зданий на линии визирования. Азимут 288°.", confidence: 0.95, source: "SRTM + OSM 3D", evidence: { dem_resolution_m: 30, buildings_in_buffer: 3, azimuth_deg: 288.5, from_floor: 1 } },
      { key: "noise_score", label: "Тишина", icon: "🤫", value: "5/100 (очень тихо)", detail: "Нет источников шума в радиусе 500м. Только лес и дюны.", confidence: 0.96, source: "OSM", evidence: { breakdown: {} } },
      { key: "walk_to_sea", label: "Пешком до моря", icon: "🚶", value: "2 мин", detail: "180 м по тропинке через дюны. Без дорог.", confidence: 0.94, source: "OSM + DEM", evidence: { distance_m: 180, crosses_highway: false } },
      { key: "air_quality", label: "Качество воздуха", icon: "🌿", value: "AQI 18 (отличный)", detail: "Сосновый лес + морской бриз. Один из лучших показателей в регионе.", confidence: 0.82, source: "OpenAQ + Open-Meteo", evidence: { aqi: 18, pm25: 5.2 } },
      { key: "weather", label: "Климат", icon: "☀️", value: "Мягкий морской", detail: "Средняя t° летом: +19°C. 230 солнечных часов за сезон.", confidence: 0.90, source: "Open-Meteo", evidence: { avg_summer_temp: 19, sunny_hours: 230 } },
      { key: "cell_coverage", label: "Связь", icon: "📶", value: "4G все операторы", detail: "Уверенный приём всех операторов. 4G LTE до 45 Мбит/с.", confidence: 0.78, source: "OpenCellID", evidence: { towers_nearby: 3, best_signal_dbm: -72 } },
    ],
    questions: [],
    sunset_ray: { azimuth: 288, length_km: 10 },
  },
  {
    id: 3,
    name: "Амалиенау Хисторик",
    address: "Калининград, ул. Красная, 24",
    lat: 54.706,
    lon: 20.483,
    floors: 3,
    facade_azimuth: 250,
    stars: 4,
    price_per_night: 7200,
    image: "🏰",
    description: "Отель в историческом районе Амалиенау. Здание 1912 года в стиле югендстиль. Рядом — парк и пруд.",
    features: [
      { key: "sunset_view", label: "Закат над Балтикой", icon: "🌅", value: "Не виден", detail: "Море в 30 км. Здания перекрывают горизонт на западе.", confidence: 0.92, source: "SRTM + OSM 3D", evidence: { dem_resolution_m: 30, buildings_in_buffer: 87, blocked_by: "9-этажный дом на ул. Театральной" } },
      { key: "noise_score", label: "Тишина", icon: "🤫", value: "38/100 (умеренно)", detail: "Рядом проспект с умеренным трафиком. Парк снижает шум.", confidence: 0.88, source: "OSM", evidence: { breakdown: { "highway=primary": { count: 1, weight: 6 }, "highway=residential": { count: 4, weight: 2 } } } },
      { key: "walk_to_sea", label: "Пешком до моря", icon: "🚶", value: "Не пешеходно", detail: "Море в 30 км. На машине — 40 мин.", confidence: 0.95, source: "OSM + DEM", evidence: { distance_m: 30200, by_car_min: 40 } },
      { key: "wikidata_history", label: "Историческое здание", icon: "🏛️", value: "Да, 1912 год", detail: "Памятник архитектуры. Югендстиль, оригинальная лепнина. Q4829371.", confidence: 0.98, source: "Wikidata", evidence: { year_built: 1912, heritage: true, wikidata_id: "Q4829371", style: "Jugendstil" } },
      { key: "night_amenities", label: "Ночная инфраструктура", icon: "🌙", value: "Театры, бары", detail: "5 мин до драмтеатра. 8 баров в радиусе 500м.", confidence: 0.90, source: "OSM", evidence: { theaters: 1, bars: 8, restaurants: 12 } },
      { key: "car_access", label: "Парковка", icon: "🚗", value: "Бесплатная, 20 мест", detail: "Подземная парковка. Зарядка для EV.", confidence: 0.93, source: "hotelier", evidence: { spots: 20, ev_charger: true, free: true } },
    ],
    questions: [
      { id: 201, feature_key: "breakfast_type", question: "Какой тип завтрака предоставляется? Включён ли он в стоимость номера? Есть ли веганские/безглютеновые опции?", status: "pending", asked_at: "2026-01-14T14:30:00Z" },
      { id: 202, feature_key: "room_view", question: "Есть ли номера с видом на парк? На каких этажах?", status: "answered", answer_raw: "Да, номера 301-310 на 3 этаже выходят окнами на парк Амалиенау. Вид на пруд и липовую аллею.", answer_parsed: { has_park_view: true, rooms: "301-310", floor: 3, view_description: "Парк Амалиенау, пруд, липовая аллея" }, asked_at: "2026-01-14T14:35:00Z" },
    ],
    sunset_ray: { azimuth: 250, length_km: 3 },
  },
  {
    id: 4,
    name: "Фишерхаус на Косе",
    address: "пос. Рыбачий, Куршская коса, ул. Ленинская, 5",
    lat: 55.098,
    lon: 20.856,
    floors: 2,
    facade_azimuth: 275,
    stars: 3,
    price_per_night: 3800,
    image: "🐟",
    description: "Аутентичный рыбацкий дом, переделанный в мини-отель. Копчёная рыба, велосипеды, тишина.",
    features: [
      { key: "sunset_view", label: "Закат над Балтикой", icon: "🌅", value: "Виден с 1 этажа", detail: "Западный фасад — прямой вид на залив и дюны. Азимут 285°.", confidence: 0.93, source: "SRTM + OSM 3D", evidence: { dem_resolution_m: 30, buildings_in_buffer: 8, azimuth_deg: 285.1, from_floor: 1 } },
      { key: "noise_score", label: "Тишина", icon: "🤫", value: "8/100 (очень тихо)", detail: "Тихая улица, нет магистралей.", confidence: 0.94, source: "OSM", evidence: { breakdown: { "highway=residential": { count: 1, weight: 2 } } } },
      { key: "walk_to_sea", label: "Пешком до моря", icon: "🚶", value: "7 мин", detail: "650 м через посёлок. Без трасс.", confidence: 0.91, source: "OSM + DEM", evidence: { distance_m: 650, crosses_highway: false } },
      { key: "wikidata_history", label: "Историческое здание", icon: "🏛️", value: "Да, ~1890 год", detail: "Рыбацкий дом XIX века. Типичная архитектура косы.", confidence: 0.85, source: "Wikidata", evidence: { year_built: 1890, heritage: false, style: "Fischerhaus" } },
      { key: "family", label: "Семейный", icon: "👨‍👩‍👧", value: "Да, но без инфраструктуры", detail: "Принимают детей, но нет спец. оборудования.", confidence: 0.80, source: "hotelier", evidence: { crib: false, playground: false, kids_menu: false } },
      { key: "air_quality", label: "Качество воздуха", icon: "🌿", value: "AQI 15 (отличный)", detail: "Лучшее качество воздуха в регионе благодаря лесу и морю.", confidence: 0.80, source: "OpenAQ", evidence: { aqi: 15, pm25: 4.1 } },
    ],
    questions: [
      { id: 301, feature_key: "bike_rental", question: "Предоставляете ли вы велосипеды для гостей? Сколько стоит аренда на день?", status: "pending", asked_at: "2026-01-16T09:00:00Z" },
    ],
    sunset_ray: { azimuth: 285, length_km: 10 },
  },
  {
    id: 5,
    name: "Кёнигсберг Плаза",
    address: "Калининград, Ленинский пр-т, 82",
    lat: 54.710,
    lon: 20.506,
    floors: 9,
    facade_azimuth: 200,
    stars: 4,
    price_per_night: 6500,
    image: "🏢",
    description: "Бизнес-отель в центре Калининграда. Панорамные окна, ресторан на крыше, вид на Кафедральный собор.",
    features: [
      { key: "sunset_view", label: "Закат над Балтикой", icon: "🌅", value: "Не виден", detail: "Городская застройка полностью перекрывает горизонт.", confidence: 0.94, source: "SRTM + OSM 3D", evidence: { dem_resolution_m: 30, buildings_in_buffer: 156, blocked_by: "Многоэтажная застройка" } },
      { key: "noise_score", label: "Тишина", icon: "🤫", value: "62/100 (шумно)", detail: "Ленинский проспект — основная магистраль города.", confidence: 0.90, source: "OSM", evidence: { breakdown: { "highway=primary": { count: 2, weight: 6 }, "highway=trunk": { count: 1, weight: 10 }, "highway=residential": { count: 5, weight: 2 } } } },
      { key: "walk_to_sea", label: "Пешком до моря", icon: "🚶", value: "Не пешеходно", detail: "Море в 35 км. На машине — 45 мин.", confidence: 0.95, source: "OSM + DEM", evidence: { distance_m: 35000, by_car_min: 45 } },
      { key: "night_amenities", label: "Ночная инфраструктура", icon: "🌙", value: "Отличная", detail: "20+ ресторанов, баров, кинотеатр в радиусе 500м.", confidence: 0.95, source: "OSM", evidence: { restaurants: 15, bars: 8, cinema: 1 } },
      { key: "car_access", label: "Парковка", icon: "🚗", value: "Подземная, 500₽/сутки", detail: "80 мест, въезд с проспекта.", confidence: 0.92, source: "hotelier", evidence: { spots: 80, ev_charger: false, free: false, price: "500₽/сутки" } },
      { key: "family", label: "Семейный", icon: "👨‍👩‍👧", value: "Да", detail: "Детская комната, кроватки, игровая зона.", confidence: 0.93, source: "hotelier", evidence: { crib: true, playground: true, kids_menu: true, kids_room: true } },
    ],
    questions: [],
    sunset_ray: { azimuth: 200, length_km: 1.5 },
  },
  {
    id: 6,
    name: "Светлый Утёс",
    address: "Светлогорск, ул. Октябрьская, 8",
    lat: 54.942,
    lon: 20.149,
    floors: 6,
    facade_azimuth: 280,
    stars: 4,
    price_per_night: 5200,
    image: "🪨",
    description: "Отель на утёсе над морем в Светлогорске. Потрясающий вид на Балтику с верхних этажей. Собственный спа.",
    features: [
      { key: "sunset_view", label: "Закат над Балтикой", icon: "🌅", value: "Виден с 4 этажа", detail: "Утёс даёт преимущество: обзор с 4 этажа. Азимут 292°.", confidence: 0.90, source: "SRTM + OSM 3D", evidence: { dem_resolution_m: 30, buildings_in_buffer: 28, azimuth_deg: 292.0, from_floor: 4, cliff_advantage_m: 12 } },
      { key: "noise_score", label: "Тишина", icon: "🤫", value: "18/100 (тихо)", detail: "Курортная зона, нет магистралей.", confidence: 0.89, source: "OSM", evidence: { breakdown: { "highway=residential": { count: 3, weight: 2 } } } },
      { key: "walk_to_sea", label: "Пешком до моря", icon: "🚶", value: "3 мин", detail: "250 м по лестнице к пляжу. Крутой спуск.", confidence: 0.92, source: "OSM + DEM", evidence: { distance_m: 250, crosses_highway: false, elevation_change_m: 25 } },
      { key: "night_amenities", label: "Ночная инфраструктура", icon: "🌙", value: "Рестораны до 22:00", detail: "4 ресторана в радиусе 300м.", confidence: 0.87, source: "OSM", evidence: { restaurants: 4, cafes: 2, max_closing: "22:00" } },
      { key: "weather", label: "Климат", icon: "☀️", value: "Мягкий морской", detail: "На 1°C теплее Калининграда благодаря утёсу.", confidence: 0.88, source: "Open-Meteo", evidence: { avg_summer_temp: 20, sunny_hours: 240 } },
      { key: "cell_coverage", label: "Связь", icon: "📶", value: "4G, отличный сигнал", detail: "Высокое расположение — прямой сигнал от вышек.", confidence: 0.82, source: "OpenCellID", evidence: { towers_nearby: 5, best_signal_dbm: -65 } },
    ],
    questions: [
      { id: 401, feature_key: "spa_services", question: "Какие спа-процедуры доступны? Включены ли они в стоимость? Нужно ли бронировать заранее?", status: "pending", asked_at: "2026-01-15T16:00:00Z" },
    ],
    sunset_ray: { azimuth: 292, length_km: 10 },
  },
  {
    id: 7,
    name: "Кошачий Двор",
    address: "Зеленоградск, ул. Ленинградская, 45",
    lat: 54.960,
    lon: 20.485,
    floors: 3,
    facade_azimuth: 275,
    stars: 3,
    price_per_night: 4500,
    image: "🐱",
    description: "Тематический отель для любителей котов. 12 котов живут в отеле. Рядом — кошачий музей и памятник коту.",
    features: [
      { key: "sunset_view", label: "Закат над Балтикой", icon: "🌅", value: "Виден с 2 этажа", detail: "Западные окна, 2 этаж. Азимут 290°.", confidence: 0.86, source: "SRTM + OSM 3D", evidence: { dem_resolution_m: 30, buildings_in_buffer: 35, azimuth_deg: 290.0, from_floor: 2 } },
      { key: "noise_score", label: "Тишина", icon: "🤫", value: "25/100 (тихо)", detail: "Спокойная улица в курортной части города.", confidence: 0.90, source: "OSM", evidence: { breakdown: { "highway=residential": { count: 2, weight: 2 } } } },
      { key: "walk_to_sea", label: "Пешком до моря", icon: "🚶", value: "5 мин", detail: "480 м через пешеходную улицу.", confidence: 0.93, source: "OSM + DEM", evidence: { distance_m: 480, crosses_highway: false } },
      { key: "family", label: "Семейный + питомцы", icon: "🐾", value: "Pet-friendly", detail: "Принимают с животными. Есть лежанки, миски, ветеринар рядом.", confidence: 0.97, source: "hotelier", evidence: { pets_allowed: true, pet_bed: true, vet_nearby: true, pet_fee: "500₽/сутки" } },
      { key: "night_amenities", label: "Ночная инфраструктура", icon: "🌙", value: "Кафе до 22:00", detail: "Кошачье кафе, 2 ресторана.", confidence: 0.88, source: "OSM", evidence: { restaurants: 2, cafes: 2, cat_cafe: true } },
      { key: "wikidata_history", label: "Район", icon: "🏛️", value: "Курортная зона с 1885", detail: "Зеленоградск — бывший Кранц, курорт с прусских времён.", confidence: 0.95, source: "Wikidata", evidence: { resort_since: 1885, former_name: "Кранц" } },
    ],
    questions: [],
    sunset_ray: { azimuth: 290, length_km: 10 },
  },
  {
    id: 8,
    name: "Янтарный Берег",
    address: "пос. Янтарный, ул. Морская, 1",
    lat: 54.950,
    lon: 20.010,
    floors: 4,
    facade_azimuth: 285,
    stars: 3,
    price_per_night: 3500,
    image: "💎",
    description: "Отель на берегу Балтики в Янтарном. Собственный пляж, карьер по добыче янтаря рядом. Можно искать янтарь после шторма!",
    features: [
      { key: "sunset_view", label: "Закат над Балтикой", icon: "🌅", value: "Виден с 1 этажа", detail: "Первая линия, прямой вид на море. Азимут 291°.", confidence: 0.96, source: "SRTM + OSM 3D", evidence: { dem_resolution_m: 30, buildings_in_buffer: 5, azimuth_deg: 291.3, from_floor: 1 } },
      { key: "noise_score", label: "Тишина", icon: "🤫", value: "10/100 (очень тихо)", detail: "Тихий посёлок, нет транзитного транспорта.", confidence: 0.93, source: "OSM", evidence: { breakdown: { "highway=residential": { count: 1, weight: 2 } } } },
      { key: "walk_to_sea", label: "Пешком до моря", icon: "🚶", value: "1 мин", detail: "50 м до пляжа. Выход прямо из отеля.", confidence: 0.97, source: "OSM + DEM", evidence: { distance_m: 50, crosses_highway: false } },
      { key: "air_quality", label: "Качество воздуха", icon: "🌿", value: "AQI 12 (превосходный)", detail: "Морской воздух, минимум загрязнений.", confidence: 0.79, source: "OpenAQ", evidence: { aqi: 12, pm25: 3.5 } },
      { key: "weather", label: "Климат", icon: "☀️", value: "Морской, ветреный", detail: "Сильные ветра — характерно для мыса. Средняя t° летом: +18°C.", confidence: 0.87, source: "Open-Meteo", evidence: { avg_summer_temp: 18, sunny_hours: 210, wind_speed_kmh: 18 } },
      { key: "family", label: "Семейный", icon: "👨‍👩‍👧", value: "Да", detail: "Песочный пляж, мелководье, детская анимация летом.", confidence: 0.91, source: "hotelier", evidence: { sandy_beach: true, shallow: true, animation: true } },
    ],
    questions: [
      { id: 501, feature_key: "amber_tours", question: "Организуете ли вы экскурсии на янтарный карьер? Можно ли самим искать янтарь на пляже?", status: "pending", asked_at: "2026-01-16T11:00:00Z" },
    ],
    sunset_ray: { azimuth: 291, length_km: 10 },
  },
];

export const routes: Route[] = [
  {
    id: 1,
    title: "3 дня в Зеленоградске для котовладельцев",
    author: "Катя и Барсик",
    description: "Маршрут для тех, кто путешествует с котами. Pet-friendly отели, кошачьи достопримечательности, тихие прогулки по променаду.",
    cover_emoji: "🐱",
    hotel_ids: [1, 7],
    key_features: ["Pet-friendly", "Тишина", "Закат над морем"],
    days: 3,
  },
  {
    id: 2,
    title: "Кёнигсберг за выходные",
    author: "Алексей И.",
    description: "Исторический маршрут: Амалиенау, Кафедральный собор, могила Канта. Отели в исторических зданиях.",
    cover_emoji: "🏰",
    hotel_ids: [3, 5],
    key_features: ["Историческое здание", "Ночная жизнь", "Парковка"],
    days: 2,
  },
  {
    id: 3,
    title: "Куршская коса: тишина и дюны",
    author: "Марина Д.",
    description: "Побег от города. Дюны, лес, море. Лучшие закаты Калининградской области. Минимум людей, максимум природы.",
    cover_emoji: "🏜️",
    hotel_ids: [2, 4],
    key_features: ["Тишина", "Закат над морем", "Качество воздуха"],
    days: 4,
  },
  {
    id: 4,
    title: "Балтийский релакс: спа и закаты",
    author: "Ольга К.",
    description: "Светлогорск и Янтарный — спа-отели на утёсах, закаты над Балтикой, янтарные сувениры.",
    cover_emoji: "🌅",
    hotel_ids: [6, 8],
    key_features: ["Закат над морем", "Спа", "Пляж рядом"],
    days: 5,
  },
];
