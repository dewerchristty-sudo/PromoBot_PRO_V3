from datetime import datetime, timedelta


class PriceCollectionScheduleManager:

    def __init__(self, config):
        self.config = config

    def next_run(self, now):
        if not self.config.times:
            return None
        for configured in self.config.times:
            candidate = datetime.combine(
                now.date(), configured, tzinfo=now.tzinfo
            )
            if candidate > now:
                return candidate
        tomorrow = now.date() + timedelta(days=1)
        return datetime.combine(
            tomorrow, self.config.times[0], tzinfo=now.tzinfo
        )

    def finite_cycle_limit(self):
        return max(len(self.config.times), 1)
