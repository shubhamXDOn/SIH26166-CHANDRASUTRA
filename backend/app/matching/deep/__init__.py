"""M4 strong-deep matcher package.

SuperPoint (Detone et al., NeurIPS 2018) + SuperGlue (Sarlin et al.,
CVPR 2020) integrated through the shared M3 candidate-correspondence
contract. Graphs in this package are reference-faithful to the official
pretrained checkpoints (verified by strict state-dict loading) and they
ONLY report observational candidate correspondences — never inliers,
trusted or registered matches.
"""