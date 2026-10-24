import math
import os
import json
import numpy as np
import rasterio
from shapely.geometry import Point

def get_dem_height(dem_path: str, lon: float, lat: float) -> float:
    """Получает высоту рельефа из DEM по координатам (lon, lat)."""
    try:
        with rasterio.open(dem_path) as src:
            # rasterio.sample принимает список кортежей (x, y), т.е. (lon, lat)
            heights = list(src.sample([(lon, lat)]))
            val = heights[0][0]
            return float(val) if not np.isnan(val) else 0.0
    except Exception:
        return 0.0

def calculate_sunset_view(hotel_geom: Point, dem_path: str, floors: int = 3) -> dict:
    """
    Вычисляет вид на закат над морем для отеля с помощью рейкастинга по DEM.
    """
    lon, lat = hotel_geom.x, hotel_geom.y
    
    # 1. Азимут заката в Калининграде летом (май-август) ~ 295° (северо-запад, над Балтикой)
    azimuth_deg = 295.0
    azimuth_rad = math.radians(azimuth_deg)
    
    # 2. Высота наблюдателя (высота земли под отелем + высота этажа * ~3 метра)
    ground_height = get_dem_height(dem_path, lon, lat)
    observer_height = ground_height + (floors * 3.0)
    
    # 3. Параметры рейкастинга
    max_dist_m = 5000  # Смотрим на 5 км вперед
    step_m = 250       # Шаг проверки каждые 250 метров
    num_points = int(max_dist_m / step_m)
    
    max_elevation_angle = -90.0 # Максимальный угол возвышения препятствия (в градусах)
    
    # Приближение метров в градусы для широты ~55° с.ш.
    m_per_deg_lat = 111000
    m_per_deg_lon = 63000
    
    visible = True
    blocking_distance = None
    
    # 4. Проход по лучу
    for i in range(1, num_points + 1):
        dist = i * step_m
        
        # Смещение по координатам в направлении азимута
        delta_lat = (dist * math.cos(azimuth_rad)) / m_per_deg_lat
        delta_lon = (dist * math.sin(azimuth_rad)) / m_per_deg_lon
        
        check_lat = lat + delta_lat
        check_lon = lon + delta_lon
        
        # Высота рельефа в точке луча
        terrain_height = get_dem_height(dem_path, check_lon, check_lat)
        
        # Угол возвышения препятствия относительно глаз наблюдателя (в градусах)
        height_diff = terrain_height - observer_height
        elevation_angle = math.degrees(math.atan2(height_diff, dist))
        
        if elevation_angle > max_elevation_angle:
            max_elevation_angle = elevation_angle
            
        # Если угол возвышения > 5°, значит что-то (гора или высокое здание) загораживает вид
        if elevation_angle > 5.0:
            visible = False
            blocking_distance = dist
            break
            
    # 5. Расчет уверенности (confidence) и минимального этажа
    if visible and max_elevation_angle < 0:
        # Идеальный вид: склон вниз к морю, ничего не мешает
        confidence = 0.92
        min_floor = max(1, floors - 1) 
    elif visible:
        confidence = 0.75
        min_floor = floors
    else:
        confidence = 0.40
        # Эвристика: сколько этажей нужно добавить, чтобы "перерасти" препятствие
        required_extra_height = abs(max_elevation_angle) * (blocking_distance or 1000) / 50
        min_floor = int(math.ceil((observer_height + required_extra_height) / 3.0))
        
    return {
        "visible": visible,
        "from_floor": min_floor,
        "azimuth": azimuth_deg,
        "months": [5, 6, 7, 8], # Май-Август: закат над водой
        "confidence": round(confidence, 2),
        "evidence": {
            "max_elevation_angle_deg": round(max_elevation_angle, 2),
            "observer_height_m": round(observer_height, 1),
            "blocking_distance_m": blocking_distance,
            "dem_resolution": "SRTM3 (~90m)"
        }
    }

# 🧪 ТЕСТОВЫЙ ЗАПУСК (чтобы проверить работу без поднятия всего API)
if __name__ == "__main__":
    # Путь к DEM из папки data (адаптируй, если запускаешь из другой папки)
    current_dir = os.path.dirname(os.path.abspath(__file__))
    dem_path = os.path.join(current_dir, "..", "..", "..", "data", "dem.tif")
    
    # Координаты отеля в Зеленоградске (из нашего fallback-набора)
    test_hotel = Point(20.4832, 54.9605)
    
    print(f"🔍 Проверка вида на закат для отеля в точке {test_hotel.x}, {test_hotel.y}...")
    print(f"📂 Путь к DEM: {os.path.abspath(dem_path)}\n")
    
    result = calculate_sunset_view(test_hotel, dem_path, floors=4)
    
    print("✅ Результат рейкастинга:")
    print(json.dumps(result, indent=2, ensure_ascii=False))