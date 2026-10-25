import asyncio
import time
from collections import deque
from datetime import datetime, timezone

from .storage import read_json, write_json


def now():
    return datetime.now(timezone.utc)


def total(per):
    up = sum(v.get('up', 0) for v in per.values())
    down = sum(v.get('down', 0) for v in per.values())
    return {'up': up, 'down': down, 'total': up + down}


class Traffic:
    def __init__(self, cfg):
        self.path = cfg.data / 'traffic.json'
        self.limit = max(0, float(cfg.env.get('TRAFFIC_LIMIT_GB', 0))) * 1024 ** 3
        self.state = read_json(self.path) or self.fresh()
        self.live = {'up': 0, 'down': 0}
        self.active = {}
        self.samples = deque(maxlen=6)
        self.dirty = False
        self.roll()

    def fresh(self):
        return {'v': 1, 'since': now().isoformat(), 'allTime': {},
                'day': {'key': now().strftime('%Y-%m-%d'), 'per': {}},
                'month': {'key': now().strftime('%Y-%m'), 'per': {}, 'baseBytes': 0}}

    def roll(self):
        for key, fmt in [('day', '%Y-%m-%d'), ('month', '%Y-%m')]:
            stamp = now().strftime(fmt)
            if self.state[key]['key'] != stamp:
                self.state[key] = {'key': stamp, 'per': {}, 'baseBytes': 0}
                self.dirty = True

    def add(self, label, up=0, down=0):
        self.roll()
        for per in (self.state['allTime'], self.state['day']['per'], self.state['month']['per']):
            bucket = per.setdefault(label, {'up': 0, 'down': 0})
            bucket['up'] += up
            bucket['down'] += down
        self.live['up'] += up
        self.live['down'] += down
        self.dirty = True

    def save(self):
        write_json(self.path, self.state)
        self.dirty = False

    async def run(self):
        ticks = 0
        while True:
            self.samples.append((time.monotonic(), self.live.copy()))
            self.roll()
            ticks += 1
            if ticks % 30 == 0 and self.dirty:
                self.save()
            await asyncio.sleep(1)

    def baseline(self, gb):
        self.roll()
        self.state['month']['baseBytes'] = round(gb * 1024 ** 3) - total(self.state['month']['per'])['total']
        self.save()

    def reset(self):
        self.state = self.fresh()
        self.live = {'up': 0, 'down': 0}
        self.samples.clear()
        self.save()

    def snapshot(self):
        self.roll()
        rates = {'upBps': 0, 'downBps': 0}
        if len(self.samples) > 1:
            first, last = self.samples[0], self.samples[-1]
            elapsed = last[0] - first[0]
            if elapsed:
                rates = {key + 'Bps': max(0, (last[1][key] - first[1][key]) / elapsed) for key in ('up', 'down')}
        used = total(self.state['month']['per'])['total'] + self.state['month'].get('baseBytes', 0)
        date = now()
        reset = date.replace(year=date.year + (date.month == 12), month=date.month % 12 + 1,
                             day=1, hour=0, minute=0, second=0, microsecond=0)
        return {'ok': True, 'keys': sorted(self.state['allTime']), 'now': date.isoformat(),
                'since': self.state['since'], 'persisted': self.path.exists(), 'file': 'traffic.json',
                'day': {**self.state['day'], **total(self.state['day']['per'])},
                'month': {**self.state['month'], **total(self.state['month']['per']), 'used': used, 'resetsAt': reset.isoformat()},
                'allTime': {'per': self.state['allTime'], **total(self.state['allTime'])},
                'active': self.active.copy(), 'live': rates,
                'limit': None if not self.limit else {'bytes': self.limit, 'used': used,
                    'remaining': max(0, self.limit - used), 'pct': used / self.limit * 100,
                    'level': 'over' if used >= self.limit else 'warn' if used >= self.limit * .8 else 'ok'}}
