import datetime
import glob
import os
import shutil
import string
import tarfile
import tempfile

from django.conf import settings
from django.utils import timezone

from celery import shared_task
from celery.utils.log import get_task_logger

from ashlar.models import RecordType

from black_spots.tasks import (forecast_segment_incidents, load_blackspot_geoms,
                               get_segments_shp, load_road_network, get_training_noprecip)
from black_spots.models import BlackSpotRecordsFile, RoadSegmentsShapefile
from data.tasks.fetch_record_csv import export_records

logger = get_task_logger(__name__)


@shared_task
def calculate_black_spots():
    """Integrates all black spot tasks into a pipeline
    Args:
        record_type_id (UUID): The record type to train black spots for
        occurred_min (datetime.datetime): Earliest event to include
        occurred_max (datetime.datetime): Latest event to include
    """
    # Get the parameters we'll use to filter down the records we want
    now = timezone.now()
    oldest = now - datetime.timedelta(days=4 * 365 + 1)
    # Note that this assumes that there is only one RecordType with this label; there's
    # no straightforward way to auto-detect this otherwise.
    record_type = RecordType.objects.filter(label=settings.BLACKSPOT_RECORD_TYPE_LABEL).first()
    roads_srid = 3395
    segments_shp_obj = RoadSegmentsShapefile.objects.all().order_by('-created').first()

    # Refresh road segments if the most recent one is more than 30 days out of date
    if not segments_shp_obj or (now - segments_shp_obj.created > datetime.timedelta(days=30)):
        try:
            # Get roads Shapefile
            roads_shp_path = load_road_network(output_srid='EPSG:{}'.format(roads_srid))
            # Get segments Shapefile
            segments_shp_obj = get_segments_shp(roads_shp_path, roads_srid)
        except:
            # Need to provide some sort of path to attempt to clean up if load_road_network
            # didn't manage to assign to the variable
            roads_shp_path = '/opt/app/lines.shp'
            raise
        finally:
            glob_path = string.replace(roads_shp_path, '.shp', '.*')
            for f in glob.glob(glob_path):
                try:
                    os.remove(f)
                except OSError:
                    pass

    # - Get events CSV
    records_csv_obj = export_records(oldest, now, record_type.pk)
    # - Match events to segments shapefile
    blackspots_output, forecast_output = get_training_noprecip(segments_shp_obj, records_csv_obj)
    # - Run Rscript to output CSV
    segments_csv = BlackSpotRecordsFile.objects.get(blackspots_output).csv.path
    forecasts_csv = forecast_segment_incidents(segments_csv, '/opt/app/forecasts.csv')
    # - Load blackspot geoms from shapefile and CSV
    # The shapefile is stored as a gzipped tarfile so we need to extract it
    tar_output_dir = tempfile.mkdtemp()
    try:
        shp_tar = RoadSegmentsShapefile.objects.get(uuid=segments_shp_obj.pk).shp_tgz.path
        with tarfile.open(shp_tar, "r:gz") as tar:
            tar.extractall(tar_output_dir)
            load_blackspot_geoms(os.path.join(tar_output_dir, 'segments', 'combined_segments.shp'),
                                 forecasts_csv, record_type.pk, roads_srid)
    finally:
        shutil.rmtree(tar_output_dir)
