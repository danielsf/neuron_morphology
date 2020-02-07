from typing import Callable, List, Dict, Tuple, Union, Optional
from functools import partial
import os

from argschema.schemas import DefaultSchema
from argschema.fields import Int, OutputDir
from argschema.sources import ArgSource

from neuron_morphology.snap_polygons.postgres_source import (
    PostgresInputConfigSchema
)
from neuron_morphology.snap_polygons.types import (
    NicePathType, PathType, PathsType, ensure_path
)


QueryEngineType = Callable[[str], List[Dict]]


def query_for_layer_polygons(
    query_engine: QueryEngineType, 
    focal_plane_image_series_id: int
    ) -> List[Dict[str, Union[NicePathType, str]]]:
    """
    """

    query = f"""
        select
            st.acronym as name,
            polygon.path as path
        from specimens sp
        join specimens spp on spp.id = sp.parent_id
        join image_series imser on imser.specimen_id = spp.id
        join sub_images si on si.image_series_id = imser.id
        join images im on im.id = si.image_id
        join treatments tm on tm.id = im.treatment_id
        join avg_graphic_objects layer on layer.sub_image_id = si.id
        join avg_group_labels label on label.id = layer.group_label_id
        join avg_graphic_objects polygon on polygon.parent_id = layer.id
        join structures st on st.id = polygon.cortex_layer_id
        where 
            imser.id = {focal_plane_image_series_id}
            and label.name in ('Cortical Layers')
            and tm.name = 'Biocytin' -- the polys are duplicated between 'Biocytin' and 'DAPI' images. Need only one of these
        """
    return [
        {
            "name": layer["name"],
            "path": ensure_path(layer["path"])
        }
        for layer in query_engine(query)
    ]



def query_for_cortical_surfaces(
    query_engine: QueryEngineType,
    focal_plane_image_series_id: int
) -> Tuple[
    Dict[str, Union[NicePathType, str]], 
    Dict[str, Union[NicePathType, str]]
]:
    """ Return the pia and white matter surface drawings for this image series
    """

    query = f"""
        select 
            polygon.path as path,
            label.name as name
        from specimens sp
        join specimens spp on spp.id = sp.parent_id
        join image_series imser on imser.specimen_id = spp.id
        join sub_images si on si.image_series_id = imser.id
        join images im on im.id = si.image_id
        join treatments tm on tm.id = im.treatment_id
        join avg_graphic_objects layer on layer.sub_image_id = si.id
        join avg_graphic_objects polygon on polygon.parent_id = layer.id
        join avg_group_labels label on label.id = layer.group_label_id
        where
            imser.id = {focal_plane_image_series_id}
            and label.name in ('Pia', 'White Matter')
            and tm.name = 'Biocytin'
    """
    results = {}
    for item in query_engine(query):
        results[item["name"]] = {
            "name": item["name"],
            "path": ensure_path(item["path"])
        }
    return results["Pia"], results["White Matter"]
    
def query_for_images(
    query_engine: QueryEngineType, 
    focal_plane_image_series_id: int,
    output_dir: str
) -> List[Dict[str, str]]:

    query = f"""
        select 
            im.jp2, 
            sl.storage_directory,
            tm.name
        from sub_images si 
        join images im on im.id = si.image_id 
        join slides sl on sl.id = im.slide_id 
        join treatments tm on tm.id = im.treatment_id
        where 
            image_series_id = {focal_plane_image_series_id}
            and tm.name in ('Biocytin', 'DAPI')
    """
    results = []
    for image in query_engine(query):
        out_fname = f"{image['name']}_{image['jp2']}"
        results.append({
            "input_path": os.path.join(
                image["storage_directory"], image["jp2"]),
            "output_path": os.path.join(output_dir, out_fname)
        })
    return results


def query_for_image_dims(
    query_engine: QueryEngineType,
    focal_plane_image_series_id: int
) -> Tuple[float, float]:
    """
    """

    query = f"""
        select 
            im.height as height,
            im.width as width
        from specimens sp
        join specimens spp on spp.id = sp.parent_id
        join image_series imser on imser.specimen_id = spp.id
        join sub_images si on si.image_series_id = imser.id
        join images im on im.id = si.image_id
        join treatments tm on tm.id = im.treatment_id
        where
            imser.id = {focal_plane_image_series_id}
            and tm.name = 'Biocytin'
    """
    result = query_engine(query)
    return result[0]["width"], result[0]["height"]


def get_inputs_from_lims(
    host: str,
    port: int,
    database: str,
    user: str,
    password: str,
    imser_id: int, 
    image_output_root: Optional[str]
):
    """ Utility for building module inputs from a direct LIMS query
    """

    # need pg8000 for this, not otherwise
    from allensdk.internal.core import lims_utilities as lu
    engine = partial(
        lu.query, 
        host=host, 
        port=port, 
        database=database, 
        user=user, 
        password=password
    )

    layer_polygons = query_for_layer_polygons(engine, imser_id)
    pia_surface, wm_surface = query_for_cortical_surfaces(engine, imser_id)
    image_width, image_height = query_for_image_dims(engine, imser_id)

    results = {
        "layer_polygons": layer_polygons,
        "pia_surface": pia_surface,
        "wm_surface": wm_surface,
        "image_dimensions": {"width": image_width, "height": image_height}
    }

    if image_output_root is not None:
        results["images"] = query_for_images(
            engine, imser_id, image_output_root)

    return results


class FromLimsSchema(PostgresInputConfigSchema):
    focal_plane_image_series_id = Int(
        description="",
        required=True
    )
    image_output_root = OutputDir(
        description="",
        required=False,
        default=None,
        allow_none=True
    )

class FromLimsSource(ArgSource):
    ConfigSchema = FromLimsSchema

    def get_dict(self):
        image_output = getattr(self, "image_output_root", None)
        return get_inputs_from_lims(
            self.host, # pylint: disable=no-member
            self.port, # pylint: disable=no-member
            self.database, # pylint: disable=no-member
            self.user, # pylint: disable=no-member
            self.password, # pylint: disable=no-member,
            self.focal_plane_image_series_id, # pylint: disable=no-member
            image_output # pylint: disable=no-member
        )