from dataclasses import dataclass

import cloudflare


@dataclass
class SRVRecord():
    name: str
    priority: int
    weight: int
    port: int
    target: str

@dataclass
class CloudFlareMapEntry:
    subdomain: str
    service_name: str
    target_port: int



class CloudFlareSRVManager:
    def __init__(self, token, domain):
        self.cf = cloudflare.Cloudflare(api_token=token)
        self.domain = domain

        zones = self.cf.zones.list()
        self.zone_id = ""
        for zone in zones:
            if zone.name == domain:
                self.zone_id = zone.id
                break
        else:
            raise Exception("Zone not found!")
        
        self._have_records = []
        self._should_records: list[SRVRecord] = []

        self._update_records()

    def _update_records(self):
        self._have_records = [record for record in self.cf.dns.records.list(zone_id=self.zone_id) if record.type == "SRV"]

        # remove all records that are not in should_records
        for record in self._have_records:
            if record.name not in [record.name for record in self._should_records]:
                try:
                    self.cf.dns.records.delete(zone_id=self.zone_id, dns_record_id=record.id)
                    self._have_records.remove(record)
                except Exception as e:
                    print(f"Failed to delete record {record.name}: {e}")

        # add all records that are not in have_records
        for record in self._should_records:
            if record.name not in [record.name for record in self._have_records]:
                try:
                    record = self.cf.dns.records.create(zone_id=self.zone_id, name=record.name, type="SRV", data={"priority": record.priority, "weight": record.weight, "port": record.port, "target": record.target})
                    if record is not None:
                        self._have_records.append(record)
                except Exception as e:
                    print(f"Failed to create record {record.name}: {e}")

        self._should_records = []
        for record in self._have_records:
            self._should_records.append(SRVRecord(name=record.name, priority=record.data.priority, weight=record.data.weight, port=record.data.port, target=record.data.target))
    
    def ensure_srv_records(self, records: list[CloudFlareMapEntry]):
        self._should_records = []
        for record in records:
            self._should_records.append(SRVRecord(name=f"{record.service_name}.{record.subdomain}.{self.domain}", priority=0, weight=5, port=record.target_port, target=self.domain))

        self._update_records()
