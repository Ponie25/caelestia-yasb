from dataclasses import dataclass
from datetime import date
import json
import logging
import math
import threading
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from PySide6.QtCore import QObject, Signal, Slot


CITY = 'Hà Nội'
FORECAST = 'https://api.open-meteo.com/v1/forecast?' + urlencode({
    'latitude': 21.0245,
    'longitude': 105.84117,
    'timezone': 'Asia/Bangkok',
    'forecast_days': 7,
    'current': 'temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m',
    'daily': 'weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,sunrise,sunset',
})


def condition(code):
    if code == 0:
        return 'sun', 'Trời quang'
    if code in (1, 2):
        return 'partly', 'Có mây'
    if code == 3:
        return 'cloud', 'Nhiều mây'
    if code in (45, 48):
        return 'fog', 'Sương mù'
    if code in (71, 73, 75, 77, 85, 86):
        return 'snow', 'Có tuyết'
    if code >= 95:
        return 'storm', 'Có dông'
    return 'rain', 'Có mưa'


@dataclass(frozen=True)
class ForecastDay:
    date: date
    code: int
    high: float
    low: float
    rain: int | None


@dataclass(frozen=True)
class Forecast:
    temperature: float
    feels_like: float
    humidity: int
    wind: float
    code: int
    days: tuple[ForecastDay, ...]
    sunrise: str = '—'
    sunset: str = '—'

    @classmethod
    def parse(cls, payload):
        current = payload['current']
        daily = payload['daily']
        days = tuple(ForecastDay(date.fromisoformat(day), code, high, low, rain)
                     for day, code, high, low, rain in zip(
            daily['time'], daily['weather_code'], daily['temperature_2m_max'],
            daily['temperature_2m_min'], daily['precipitation_probability_max'], strict=True,
        ))
        if not days:
            raise ValueError('Empty weather forecast')
        values = [current[key] for key in ('temperature_2m', 'apparent_temperature', 'relative_humidity_2m',
                                           'wind_speed_10m', 'weather_code')]
        values.extend(value for day in days for value in (day.code, day.high, day.low))
        if not all(math.isfinite(value) for value in values):
            raise ValueError('Invalid weather values')
        return cls(current['temperature_2m'], current['apparent_temperature'], current['relative_humidity_2m'],
                   current['wind_speed_10m'], current['weather_code'], days,
                   daily['sunrise'][0].partition('T')[2] or '—', daily['sunset'][0].partition('T')[2] or '—')


class Weather(QObject):
    changed = Signal()
    completed = Signal(object)

    def __init__(self):
        super().__init__()
        self.forecast = None
        self.updated = None
        self.loading = False
        self.failed = False
        self.next_refresh = 0.0
        self.completed.connect(self._complete)

    def refresh(self, force=False):
        if self.loading or (not force and time.monotonic() < self.next_refresh):
            return
        self.loading = True
        self.changed.emit()
        threading.Thread(target=self._fetch, daemon=True, name='Hanoi forecast').start()

    def _fetch(self):
        try:
            request = Request(FORECAST, headers={'User-Agent': 'YASB Caelestia Dashboard'})
            with urlopen(request, timeout=8) as response:
                forecast = Forecast.parse(json.load(response))
        except (OSError, ValueError, KeyError, TypeError):
            logging.info('Hanoi forecast could not refresh', exc_info=True)
            forecast = None
        self.completed.emit(forecast)

    @Slot(object)
    def _complete(self, forecast):
        self.loading = False
        self.failed = forecast is None
        self.next_refresh = time.monotonic() + (60 if self.failed else 1200)
        if forecast is not None:
            self.forecast = forecast
            self.updated = time.time()
        self.changed.emit()
