# This file contains dataset implementations to have an easy to use
# interface for using RETURNN for regression.
# Applications are for example speech enhancement or mask estimations

__author__ = 'menne'

import os
from collections import deque
import numpy as np
import h5py

from CachedDataset2 import CachedDataset2
from Dataset import DatasetSeq


class StereoDataset(CachedDataset2):
  """The purpose of this dataset is to be a base dataset for datasets which
  have an easy to use interface for using RETURNN as a regression tool
  """

  def __init__(self, **kwargs):
    """constructor"""
    super(StereoDataset, self).__init__(**kwargs)

  @property
  def num_seqs(self):
    """returns the number of sequences of the dataset

    :rtype: int
    """
    if self._num_seqs is not None:
      return self._num_seqs
    raise NotImplementedError

  def _collect_single_seq(self, seq_idx):
    """returns the sequence specified by the index seq_idx

    :type seq_idx: int
    :rtype: DatasetSeq | None
    :returns DatasetSeq or None if seq_idx >= num_seqs.
    """
    raise NotImplementedError


class StereoHdfDataset(StereoDataset):
  """A stereo dataset which needs an hdf file as input. The hdf file
  is supposed to always have group 'inputs' and for the training data it
  also needs to contain the group 'outputs'. Each group is supposed to
  contain one dataset per sequence. The names of the datasets are supposed
  to be consecutive numbers starting at 0.

  The datasets are 2D numpy arrays, where dimension 0 is the time axis and
  dimension 1 is the feature axis. Therefore dimension 0 of the 'input'
  dataset and the respective 'output' dataset need to be the same.
  """

  def __init__(self, hdfFile, num_outputs=None, normalizationFile=None,
               **kwargs):
    """constructor

    :type hdfFile: string
    :param hdfFile: path to the hdf file if a bundle file is given (*.bundle)
                    all hdf files listed in the bundle file will be used for
                    the dataset. It is assumed that a *.bundle file contains
                    an absolute path to one hdf file per line.
    :type num_outputs: int
    :param num_outputs: this needs to be set if the stereo data hdf file
                        only contains 'inputs' data (e.g. for the extraction
                        process). Only if no 'outputs' data exists in the hdf
                        file num_outputs is used.
    :type normalizationFile: string
    :param normalizationFile: path to a HDF file with normalization data.
                              The file is optional: if it is not provided then
                              no normalization is performed.
                              The file should contain two datasets: "mean" and
                              "variance".
                              Both datasets are optional e.g. if only "mean" is
                              provided then only mean normalization will be
                              made or e.g. if only "variance" is provided then
                              only variance normalization i.e. scaling will be
                              made.
                              The datasets "mean" and "variance" should have
                              the same dimensionality as a feature in the
                              dataset. E.g. an input dataset has a shape
                              (TimeFrames, FrequencyBins) which means that a
                              feature has a shape (FrequencyBins) and therefore
                              "mean" and "variance" must have the same shape
                              (FrequencyBins).
    """
    super(StereoHdfDataset, self).__init__(**kwargs)

    # properties of the object which will be set further
    self.num_inputs = None
    self.num_outputs = None
    self._filePaths = None
    self._fileHandlers = None
    self._seqMap = None
    self._mean = None
    self._variance = None

    if not os.path.isfile(hdfFile):
      raise IOError(hdfFile + ' does not exits')
    self._initHdfFileHandlers(hdfFile)

    # set number of sequences in the dataset
    self._num_seqs = self._calculateNumberOfSequences()

    if normalizationFile is not None:
      self._setNormalization(normalizationFile)

    self._setInputAndOutputDimensions(num_outputs)

  def _initHdfFileHandlers(self, hdfFile):
    """Initialize HDF file handlers

    :type hdfFile: string
    :param hdfFile: path to an HDF file with sequences or to a bundle file
                    which should contain one path to an HDF file per line
    """
    self._filePaths = []
    self._fileHandlers = []
    if hdfFile.endswith('.bundle'):
      # a bundle file containing a list of hdf files is given
      with open(hdfFile, 'r') as f:
        for l in f:
          hdfFilePath = l.strip()
          if not hdfFilePath:
            continue
          self._filePaths.append(hdfFilePath)
          self._fileHandlers.append(h5py.File(hdfFilePath, 'r'))
    else:
      # only a single hdf file is given
      self._filePaths.append(hdfFile)
      self._fileHandlers.append(h5py.File(hdfFile, 'r'))

  def _calculateNumberOfSequences(self):
    """Calculate and return the number of sequences in the dataset.
    This method also initializes a sequences map which maps sequence
    indices into HDF file handlers.

    :rtype: int
    :return: the number of sequences in the dataset
    """
    # initialize a sequence map to map the sequence index
    # from an hdf file into the corresponding
    # hdfFile and hdf-dataset name,
    # but it could e.g. be used for shuffling sequences as well
    self._seqMap = {}
    seqCounter = 0
    for fhIdx, fh in enumerate(self._fileHandlers):
      for k in fh['inputs'].keys():
        self._seqMap[seqCounter] = (fhIdx, k)
        seqCounter += 1
    return seqCounter

  def _setNormalization(self, normalizationFile):
    """Set optional normalization (mean and variance).
    Mean and variance are set only if they are provided.

    :type normalizationFile: string
    :param normalizationFile: path to an HDF normalization file which contains
                              optional datasets "mean" and "variance".
    """
    if not os.path.isfile(normalizationFile):
      raise IOError(normalizationFile + ' does not exist')
    with h5py.File(normalizationFile, mode='r') as f:
      if 'mean' in f:
        self._mean = f['mean'][...]
      if 'variance' in f:
        self._variance = f['variance'][...]

  def _setInputAndOutputDimensions(self, num_outputs):
    """Set properties which correspond to input and output dimensions.

    :type num_outputs: int
    :param num_outputs: dimensionality of output features. used only if
                        the dataset does not have output features.
    """
    someSequence = self._collect_single_seq(0)
    self.num_inputs = someSequence.get_data('data').shape[1]
    if 'outputs' in self._fileHandlers[0]:
      self.num_outputs = {
        'classes': (someSequence.get_data('classes').shape[1], 2)
      }
    else:
      # in this case no output data is in the hdf file and
      # therfore the output dimension needs to be given
      # as an argument through the config file
      if num_outputs is None:
        raise ValueError(
          'if no output data is contained in StereoDataset'
          ' the output dimension has to be specified by num_outputs'
        )
      self.num_outputs = {'classes': (num_outputs, 2)}

  def get_data_dim(self, key):
    """This is copied from CachedDataset2 but the assertion is
    removed (see CachedDataset2.py)

    :type key: str
    :rtype: int
    :return: number of classes, no matter if sparse or not
    """
    if key == 'data':
      return self.num_inputs
    if key in self.num_outputs:
      d = self.num_outputs[key][0]
      return d
    self._load_something()
    if len(self.added_data[0].get_data(key).shape) == 1:
      return super(CachedDataset2, self).get_data_dim(key)  # unknown
    assert len(self.added_data[0].get_data(key).shape) == 2
    return self.added_data[0].get_data(key).shape[1]

  def __del__(self):
    """Closes HDF file handlers.
    """
    for fh in self._fileHandlers:
      try:
        fh.close()
      except:
        pass

  @property
  def num_seqs(self):
    """Returns the number of sequences of the dataset

    :rtype: (int)
    :return: the number of sequences of the dataset.
    """
    # has been set during initialization of dataset ...
    if self._num_seqs is not None:
      return self._num_seqs

    # ... but for some reason _num_seqs is not set at specific points in the
    # execution of rnn.py therefore the following is a saveguard to fall back on
    self._num_seqs = self._calculateNumberOfSequences()
    return self._num_seqs

  def _collect_single_seq(self, seq_idx):
    """Returns the sequence specified by the index seq_idx.
    Normalization is applied to the input features if mean and variance
    have been specified during dataset creating (see the constructor).

    :type seq_idx: int
    :rtype: DatasetSeq | None
    :returns: None if seq_idx >= num_seqs or the corresponding sequence.
    """
    if seq_idx >= self.num_seqs:
      return None

    seqMapping = self._seqMap[seq_idx]
    fileIdx = seqMapping[0]
    datasetName = seqMapping[1]
    fileHandler = self._fileHandlers[fileIdx]
    inputFeatures = fileHandler['inputs'][datasetName][...]
    targets = None
    if 'outputs' in fileHandler:
      targets = fileHandler['outputs'][datasetName][...]

    # optional normalization
    if self._mean is not None:
      inputFeatures -= self._mean
    if self._variance is not None:
      inputFeatures /= np.sqrt(self._variance)

    return DatasetSeq(seq_idx, inputFeatures, targets)


class DatasetWithTimeContext(StereoHdfDataset):
  """This dataset composes a context feature by stacking together time frames.
  """

  def __init__(self, hdfFile, tau=1, **kwargs):
    """Constructor

    :type hdfFile: string
    :param hdfFile: see the StereoHdfDataset
    :type tau: int
    :param tau: how many time frames should be on the left and on the right.
                E.g. if tau = 2 then the context feature will be created
                by stacking two neighboring time frames from left and
                two neighboring time frames from right:
                newInputFeature = [ x_{t-2}, x_{t-1}, x_t, x_{t+1}, x_{t+2} ].
                In general new feature will have shape
                (2 * tau + 1) * originalFeatureDimensionality
                Output features are not changed.
    :type kwargs: dictionary
    :param kwargs: the rest of the arguments passed to the StereoHdfDataset
    """
    if tau <= 0:
      raise ValueError('context parameter tau should be greater than zero')
    self._tau = tau
    super(DatasetWithTimeContext, self).__init__(hdfFile, **kwargs)

  def _collect_single_seq(self, seq_idx):
    """this method implements stacking the features

    :type seq_idx: int
    :param seq_idx: index of a sequence
    :rtype: DatasetSeq
    :return: DatasetSeq
    """
    if seq_idx >= self.num_seqs:
      return None
    originalSeq = super(DatasetWithTimeContext, self)._collect_single_seq(
      seq_idx
    )
    inputFeatures = originalSeq.get_data('data')
    frames, bins = inputFeatures.shape
    leftContext = deque()
    rightContext = deque()
    inFeatWithContext = []
    for i in range(self._tau):
      leftContext.append(np.zeros(bins))
      if i + 1 < frames:
        rightContext.append(inputFeatures[i + 1, ...])
      else:
        rightContext.append(np.zeros(bins))
    for t in range(frames):
      f = inputFeatures[t, ...]
      newFeature = np.concatenate(
        [
          np.concatenate(leftContext, axis=0),
          f,
          np.concatenate(rightContext, axis=0)
        ],
        axis=0
      )
      inFeatWithContext.append(newFeature)
      leftContext.popleft()
      leftContext.append(f)
      rightContext.popleft()
      if t + 1 + self._tau < frames:
        rightContext.append(inputFeatures[t + 1 + self._tau, ...])
      else:
        rightContext.append(np.zeros(bins))
    inputFeatures = np.array(inFeatWithContext)
    targets = None
    if 'classes' in originalSeq.get_data_keys():
      targets = originalSeq.get_data('classes')
    return DatasetSeq(seq_idx, inputFeatures, targets)