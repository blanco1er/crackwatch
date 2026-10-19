"""Tiny key-value layer: DynamoDB in the cloud, memory locally. One table, (pk, sk) keys, TTL attribute `ttl`."""
from __future__ import annotations

import json
import time
from decimal import Decimal


def _to_ddb(o):
    return json.loads(json.dumps(o, default=str), parse_float=Decimal)


def _from_ddb(o):
    if isinstance(o, list):
        return [_from_ddb(v) for v in o]
    if isinstance(o, dict):
        return {k: _from_ddb(v) for k, v in o.items()}
    if isinstance(o, Decimal):
        return int(o) if o == int(o) else float(o)
    return o


class MemStore:
    def __init__(self):
        self.items = {}

    def put(self, pk, sk, item: dict, ttl_days: float | None = None):
        row = dict(item)
        if ttl_days:
            row["ttl"] = int(time.time() + ttl_days * 86400)
        self.items[(pk, sk)] = json.loads(json.dumps(row, default=str))

    def get(self, pk, sk):
        return self.items.get((pk, sk))

    def incr(self, pk, sk, amount=1, ttl_days: float | None = 3) -> int:
        row = self.items.setdefault((pk, sk), {"n": 0})
        row["n"] += amount
        return row["n"]

    def query(self, pk, prefix=""):
        return [dict(v, sk=k[1]) for k, v in sorted(self.items.items()) if k[0] == pk and k[1].startswith(prefix)]


class DynamoStore:
    def __init__(self, table_name: str, region: str | None = None):
        import boto3
        self.table = boto3.resource("dynamodb", region_name=region).Table(table_name)

    def put(self, pk, sk, item: dict, ttl_days: float | None = None):
        row = dict(item, pk=pk, sk=sk)
        if ttl_days:
            row["ttl"] = int(time.time() + ttl_days * 86400)
        self.table.put_item(Item=_to_ddb(row))

    def get(self, pk, sk):
        r = self.table.get_item(Key={"pk": pk, "sk": sk}).get("Item")
        return _from_ddb(r) if r else None

    def incr(self, pk, sk, amount=1, ttl_days: float | None = 3) -> int:
        r = self.table.update_item(Key={"pk": pk, "sk": sk},
                                   UpdateExpression="ADD n :a SET #t = if_not_exists(#t, :ttl)",
                                   ExpressionAttributeNames={"#t": "ttl"},
                                   ExpressionAttributeValues={":a": amount, ":ttl": int(time.time() + (ttl_days or 3) * 86400)},
                                   ReturnValues="UPDATED_NEW")
        return int(r["Attributes"]["n"])

    def query(self, pk, prefix=""):
        from boto3.dynamodb.conditions import Key
        cond = Key("pk").eq(pk) & Key("sk").begins_with(prefix) if prefix else Key("pk").eq(pk)
        out, kw = [], {}
        while True:
            r = self.table.query(KeyConditionExpression=cond, **kw)
            out += [_from_ddb(i) for i in r.get("Items", [])]
            if "LastEvaluatedKey" not in r:
                return out
            kw["ExclusiveStartKey"] = r["LastEvaluatedKey"]
