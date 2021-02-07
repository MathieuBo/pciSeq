import os
import pandas as pd
import numpy as np
import tempfile
import platform
from pathlib import Path
from scipy.sparse import coo_matrix, save_npz, load_npz
from pciSeq.src.cell_call.main import VarBayes
from pciSeq.src.preprocess.spot_labels import stage_data
from pciSeq.src.viewer.utils import splitter_mb, content
from pciSeq import config
import logging

logger = logging.getLogger()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s:%(levelname)s:%(message)s"
)

ROOT_DIR = os.path.dirname(os.path.realpath(__file__))


def fit(iss_spots, coo, scRNAseq, opts=None):
    """
    Main entry point for pciSeq.

    Parameters
    ----------
    iss_spots : pandas.DataFrame
        Index:
            RangeIndex
        Columns:
            Name: Gene, dtype: string, The gene name
            Name: x, dtype: int64, X-axis coordinate of the spot
            Name: y, dtype: int64, Y-axis coordinate of the spot

    coo : scipy.sparse.coo_matrix
        A label image array as a coo_matrix datatype. The label denote
        which cell the corresponding pixel 'belongs' to. If label is
        zero, the pixel is on the background

    scRNAseq : pandas.DataFrame
        Index:
            The gene name
        Columns:
            The column headers are the cell classes and the data are uint32

    opts : dictionary (Optional)
        A dictionary to pass-in user-defined hyperparameter values. They override the default
        values as these are set by the config.py file. For example to exclude genes Npy and
        Vip you can define opts as:
            opts = {'exclude_genes': ['Npy', 'Vip']}
        and pass that dict to the fit function as the last argument

    Returns
    ------
    cellData : pandas.DataFrame
        Index:
            RangeIndex
        Columns:
            Name: Cell_Num, dtype: int64, The label of the cell
            Name: X, dtype: float64, X-axis coordinate of the cell centroid
            Name: Y, dtype: float64, Y-axis coordinate of the cell centroid
            Name: Genenames, dtype: Object, array-like of the genes assinged to the cell
            Name: CellGeneCount, dtype: Object,array-like of the corresponding gene counts
            Name: ClassName, dtype: Object, array-like of the genes probable classes for the cell
            Name: Prob, dtype: Object, array-like array-like of the corresponding cell class probabilities

    geneData : pandas.DataFrame
        Index:
            RangeIndex
        Columns:
            Name: Gene, dtype: string, The gene name
            Name: Gene_id, dtype: int64, The gene id, the position of the gene if all genes are sorted.
            Name: x, dtype: int64, X-axis coordinate of the spot
            Name: y, dtype: int64, Y-axis coordinate of the spot
            Name: neighbour, dtype: int64, the label of the cell which is more likely to 'raise' the spot. If zero then the spot is a misread.
            Name: neighbour_array, dtype: Object, array-like with the labels of the 4 nearest cell. The last is always the background and has label=0
            Name: neighbour_prob, dtype: Object, array-like with the prob the corresponding cell from neighbour_array has risen the spot.
    """

    # 1. get the hyperparameters
    cfg = init(opts)

    # 2. prepare the data
    logger.info('Preprocessing data')
    _cells, cell_boundaries, _spots = stage_data(iss_spots, coo)

    # 3. cell typing
    logger.info('Start cell typing')
    cellData, geneData = cell_type(_cells, _spots, scRNAseq, cfg)
    logger.info('Done')

    save_data = True
    if save_data:
        write_to_disk(cellData, geneData, cell_boundaries)
    return cellData, geneData


def cell_type(_cells, _spots, scRNAseq, ini):
    # 1. run the cell calling algo
    varBayes = VarBayes(_cells, _spots, scRNAseq, ini)
    cellData, geneData = varBayes.run()

    return cellData, geneData


def init(opts):
    """
    Reads the opts dict and if not None, it will override the default parameter value by
    the value that the dictionary key points to.
    If opts is None, then the default values as these specified in the config.py file
    are used without any change.
    """

    cfg = config.DEFAULT
    if opts is not None:
        default_items = set(cfg.keys())
        user_items = set(opts.keys())
        assert user_items.issubset(default_items), ('Options passed-in should be a dict with keys: %s ' % default_items)
        for item in opts.items():
            if isinstance(item[1], (int, float, list)):
                val = item[1]
            # elif isinstance(item[1], list):
            #     val = item[1]
            else:
                raise TypeError("Only integers, floats and lists are allowed")
            cfg[item[0]] = val
            logger.info('%s is set to %s' % (item[0], cfg[item[0]]))

    return cfg


def write_to_disk(cellData, geneData, cell_boundaries):
    temp_dir = Path("/tmp" if platform.system() == "Darwin" else tempfile.gettempdir())

    out_dir = os.path.join(temp_dir, 'pciSeq')
    if not os.path.exists(out_dir):
        os.makedirs(out_dir)

    cellData.to_csv(os.path.join(out_dir, 'cellData.tsv'), sep='\t', index=False)
    logger.info('Saved at %s' % (os.path.join(out_dir, 'cellData.tsv')))

    geneData.to_csv(os.path.join(out_dir, 'geneData.tsv'), sep='\t', index=False)
    logger.info('Saved at %s' % (os.path.join(out_dir, 'geneData.tsv')))

    cell_boundaries.to_csv(os.path.join(out_dir, 'cell_boundaries.tsv'), sep='\t', index=False)
    logger.info('Saved at %s' % (os.path.join(out_dir, 'cell_boundaries.tsv')))

    # Write to the disk as tsv of 99MB each
    splitter_mb(cellData, os.path.join(out_dir, 'cellData'), 99)
    content(os.path.join(out_dir, 'cellData'))

    splitter_mb(geneData, os.path.join(out_dir, 'geneData'), 99)
    content(os.path.join(out_dir, 'geneData'))

    splitter_mb(cell_boundaries, os.path.join(out_dir, 'cell_boundaries'), 99)
    content(os.path.join(out_dir, 'cell_boundaries'))


if __name__ == "__main__":

    # read some demo data
    _iss_spots = pd.read_csv(os.path.join(ROOT_DIR, 'data', 'mouse', 'ca1', 'iss', 'spots.csv'))
    _coo = load_npz(os.path.join(ROOT_DIR, 'data', 'mouse', 'ca1', 'segmentation', 'label_image.coo.npz'))

    _scRNAseq = pd.read_csv(os.path.join(ROOT_DIR, 'data', 'mouse', 'ca1', 'scRNA', 'scRNAseq.csv.gz'),
                            header=None, index_col=0, compression='gzip', dtype=object)
    _scRNAseq = _scRNAseq.rename(columns=_scRNAseq.iloc[0], copy=False).iloc[1:]
    _scRNAseq = _scRNAseq.astype(np.float).astype(np.uint32)

    # main task
    # _opts = {'max_iter': 10}
    fit(_iss_spots, _coo, _scRNAseq)

