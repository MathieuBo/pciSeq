"""
Functions to prepare the data for pciSeq. The label image and spots are parsed and if a spot
lies within the cell boundaries then the corresponding cell id is recorded.
Cell centroids and cell areas are also calculated.
"""

import numpy as np
import pandas as pd
import skimage.measure as skmeas
from typing import Tuple
from scipy.sparse import coo_matrix, csr_matrix
from pciSeq.src.preprocess.cell_borders import extract_borders_dip
from pciSeq.src.cell_call.log_config import logger


def inside_cell(label_image, spots) -> np.array:
    if isinstance(label_image, coo_matrix):
        label_image = label_image.tocsr()
    elif isinstance(label_image, np.ndarray):
        label_image = csr_matrix(label_image)
    elif isinstance(label_image, csr_matrix):
        pass
    else:
        raise Exception('label_image should be of type "csr_matrix" ')
    m = label_image[spots.y, spots.x]
    out = np.asarray(m)
    return out[0]


def remap_labels(coo):
    """
    Used for debugging/sanity checking only. It resuffles the label_image
    """
    coo_max = coo.data.max()
    _keys = 1 + np.arange(coo_max)
    _vals = _keys.copy()
    np.random.shuffle(_vals)
    d = dict(zip(_keys, _vals))
    new_data = np.array([d[x] for x in coo.data]).astype(np.uint64)
    out = coo_matrix((new_data, (coo.row, coo.col)), shape=coo.shape)
    return out


def reorder_labels(coo):
    """
    rearranges the labels so that they are a sequence of integers
    """
    label_image = coo.toarray()
    _, idx = np.unique(label_image.flatten(), return_inverse=True)
    return coo_matrix(idx.reshape(label_image.shape))


def stage_data(spots: pd.DataFrame, coo: coo_matrix) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Reads the spots and the label image that are passed in and calculates which cell (if any) encircles any
    given spot within its boundaries. It also retrieves the coordinates of the cell boundaries, the cell
    centroids and the cell area
    """

    if coo.data.max() != len(set(coo.data)):
        logger.info(' The labels in the label image do not seem to be a sequence of successive integers. Relabelling the label image.')
        coo = reorder_labels(coo)

    logger.info(' Number of spots passed-in: %d' % spots.shape[0])
    logger.info(' Number of segmented cells: %d' % len(set(coo.data)))
    logger.info(' Segmentation array implies that image has width: %dpx and height: %dpx' % (coo.shape[1], coo.shape[0]))
    mask_x = (spots.x >= 0) & (spots.x <= coo.shape[1])
    mask_y = (spots.y >= 0) & (spots.y <= coo.shape[0])
    spots = spots[mask_x & mask_y]

    # 1. Find which cell the spots lie within
    inc = inside_cell(coo.tocsr(), spots)
    spots = spots.assign(label=inc)

    # 2. Get cell centroids and area
    props = skmeas.regionprops(coo.toarray().astype(np.int32))
    props_df = pd.DataFrame(data=[(d.label, d.area, d.centroid[1], d.centroid[0]) for d in props],
                      columns=['label', 'area', 'x_cell', 'y_cell'])

    # 3. Get the cell boundaries
    cell_boundaries = extract_borders_dip(coo.toarray().astype(np.uint32), 0, 0, [0])

    assert props_df.shape[0] == cell_boundaries.shape[0] == np.unique(coo.data).shape[0]
    assert set(spots.label[spots.label > 0]) <= set(props_df.label)

    cells = props_df.merge(cell_boundaries)
    cells.sort_values(by=['label', 'x_cell', 'y_cell'])
    assert cells.shape[0] == cell_boundaries.shape[0] == props_df.shape[0]

    # join spots and cells on the cell label so you can get the x,y coords of the cell for any given spot
    spots = spots.merge(cells, how='left', on=['label'])

    _cells = cells[['label', 'area', 'x_cell', 'y_cell']].rename(columns={'x_cell': 'x', 'y_cell': 'y'})
    _cell_boundaries = cells[['label', 'coords']].rename(columns={'label': 'cell_id'})
    _spots = spots[['x', 'y', 'label', 'Gene', 'x_cell', 'y_cell']].rename(columns={'Gene': 'target', 'x': 'x_global', 'y': 'y_global'})

    return _cells, _cell_boundaries, _spots

