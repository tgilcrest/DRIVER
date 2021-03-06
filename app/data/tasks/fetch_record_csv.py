import csv
from django.core.files import File
from collections import namedtuple
import tempfile
import re

from celery import shared_task

from ashlar.models import Record
from black_spots.models import BlackSpotRecordsFile


# Keys which cannot be usefully exported to csv
DROPPED_KEYS = ['media']
# static record fields
RECORD_FIELDS = ['record_id', 'created', 'modified', 'occurred_from',
                 'occurred_to', 'lat', 'lon', 'location_text',
                 'city', 'city_district', 'county', 'neighborhood', 'road',
                 'state', 'weather', 'light']


def FIELD_TRANSFORMS():
    def date_iso(d):
        return d.isoformat()

    FieldTransform = namedtuple('FieldTransform', ['field', 'transform'])
    return {
        'record_id': FieldTransform(field='uuid', transform=lambda uuid: str(uuid)),
        'created': FieldTransform(field='created', transform=date_iso),
        'modified': FieldTransform(field='modified', transform=date_iso),
        'occurred_from': FieldTransform(field='occurred_from', transform=date_iso),
        'occurred_to': FieldTransform(field='occurred_to', transform=date_iso),
        'lat': FieldTransform(field='geom', transform=lambda geom: geom.y),
        'lon': FieldTransform(field='geom', transform=lambda geom: geom.x),
    }


@shared_task
def export_records(occurred_min, occurred_max, record_type_id):
    def to_utf8(s):
        """Convert to utf8 encoding and strip special whitespace/commas for csv writing"""
        if isinstance(s, str):
            return re.sub(r'[\r\n\t]', '', s)
        elif isinstance(s, unicode):
            return re.sub(r'[\r\n\t]', '', s).encode('utf-8')
        elif s is None:
            return unicode('').encode('utf-8')
        else:
            return re.sub(r'[\r\n\t]', '', unicode(s)).encode('utf-8')

    records = Record.objects.filter(
        occurred_from__gte=occurred_min,
        occurred_to__lte=occurred_max,
        schema__record_type_id=record_type_id
    )

    try:
        record_type = records[0].schema.record_type
        schema = record_type.get_current_schema()
    except IndexError:
        raise Exception('No records in result set')

    jsonschema = schema.schema
    details = {
        key: subschema for key, subschema in jsonschema['definitions'].viewitems()
        if 'details' in subschema and subschema['details'] is True
    }
    details_key = details.keys()[0]
    record_detail_fields = [
        key for key, val in details[details_key]['properties'].viewitems()
        if (
                'options' not in val or
                'hidden' not in val['options'] or
                val['options']['hidden'] is False
        ) and (
            key not in DROPPED_KEYS
        )
    ]
    csv_columns = RECORD_FIELDS + record_detail_fields
    transforms = FIELD_TRANSFORMS()
    row_dicts = []
    for record in records:
        row = dict()
        for field in RECORD_FIELDS:
            if field in transforms:
                ft = transforms[field]
                row[field] = to_utf8(ft.transform(getattr(record, ft.field)))
            else:
                row[field] = to_utf8(getattr(record, field))
        for field in record_detail_fields:
            if field in transforms:
                ft = transforms[field]
                if ft.field in record.data[details_key]:
                    row[field] = to_utf8(ft.transform(record.data[details_key][ft.field]))
                else:
                    row[field] = ''
            else:
                if field in record.data[details_key]:
                    row[field] = to_utf8(record.data[details_key][field])
                else:
                    row[field] = ''
        row_dicts.append(row)

    with tempfile.SpooledTemporaryFile(max_size=128000000) as csvfile:  # 128 mb
        writer = csv.DictWriter(csvfile, fieldnames=csv_columns)
        writer.writeheader()
        writer.writerows(row_dicts)
        store = BlackSpotRecordsFile()
        #  seek to the beginning of file so it can be read into the store
        csvfile.seek(0, 0)
        saved_filename = '{}.csv'.format(store.uuid)
        store.csv.save(saved_filename, File(csvfile))
        return store.uuid
