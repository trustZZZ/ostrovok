"""
API роутер маршрутов.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_db

router = APIRouter()

@router.get("/routes")
async def list_routes(db: AsyncSession = Depends(get_db)):
    """Витрина маршрутов."""
    from sqlalchemy import select
    from app.models import Route
    
    result = await db.execute(select(Route))
    routes = result.scalars().all()
    
    return [
        {
            "id": r.id,
            "title": r.title,
            "author": r.author,
            "description": r.description,
            "points": r.points,
            "hotel_ids": r.hotel_ids,
        }
        for r in routes
    ]

@router.get("/routes/{route_id}")
async def get_route(route_id: int, db: AsyncSession = Depends(get_db)):
    """Детали маршрута с подобранными отелями."""
    from sqlalchemy import select
    from app.models import Route, Hotel, HotelFeature
    
    result = await db.execute(select(Route).where(Route.id == route_id))
    route = result.scalar_one_or_none()
    
    if not route:
        return {"error": "Route not found"}
    
    # Загружаем отели маршрута
    hotels_result = await db.execute(
        select(Hotel).where(Hotel.id.in_(route.hotel_ids or []))
    )
    hotels = hotels_result.scalars().all()
    
    # Загружаем фичи для каждого отеля
    hotels_with_features = []
    for hotel in hotels:
        features_result = await db.execute(
            select(HotelFeature).where(HotelFeature.hotel_id == hotel.id)
        )
        features = features_result.scalars().all()
        
        hotels_with_features.append({
            "id": hotel.id,
            "name": hotel.name,
            "address": hotel.address,
            # Point(x, y): x — долгота, y — широта
            "lat": float(hotel.geom.y) if hotel.geom else None,
            "lon": float(hotel.geom.x) if hotel.geom else None,
            "features": [
                {
                    "key": f.feature_key,
                    "value": f.value,
                    "confidence": f.confidence,
                    "source": f.source,
                }
                for f in features
            ],
        })
    
    return {
        "id": route.id,
        "title": route.title,
        "author": route.author,
        "description": route.description,
        "hotels": hotels_with_features,
    }
