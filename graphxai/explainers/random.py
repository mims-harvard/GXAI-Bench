from typing import Optional

import torch
from torch_geometric.utils import k_hop_subgraph
from torch_geometric.utils.num_nodes import maybe_num_nodes

from graphxai.explainers._base import _BaseExplainer
from graphxai.utils.constants import EXP_TYPES


class RandomExplainer(_BaseExplainer):
    """
    Random Explanation for GNNs
    """
    def __init__(self, model):
        super().__init__(model)

    def get_explanation_node(self, node_idx: int, x: torch.Tensor,
                             edge_index: torch.Tensor, num_hops: Optional[int] = None):
        """
        Get the explanation for a node.

        Args:
            node_idx (int): index of the node to be explained
            x (torch.Tensor, [n x d]): tensor of node features
            edge_index (torch.Tensor, [2 x m]): edge index of the graph

        Returns:
            exp (dict):
                exp['feature_imp'] (torch.Tensor, [d]): feature mask explanation
                exp['edge_imp'] (torch.Tensor, [m]): k-hop edge importance
                exp['node_imp'] (torch.Tensor, [m]): k-hop node importance
            khop_info (4-tuple of torch.Tensor):
                0. the nodes involved in the subgraph
                1. the filtered `edge_index`
                2. the mapping from node indices in `node_idx` to their new location
                3. the `edge_index` mask indicating which edges were preserved
        """
        num_hops = self.L if num_hops is None else num_hops
        khop_info = k_hop_subgraph(node_idx, num_hops, edge_index)

        exp = {k: None for k in EXP_TYPES}
        exp['feature_imp'] = torch.randn(x[0, :].shape)
        exp['edge_imp'] = torch.randn(edge_index[0, :].shape)

        return exp, khop_info

    def get_explanation_graph(self, x: torch.Tensor, edge_index: torch.Tensor,
                              num_nodes : int = None):
        """
        Get the explanation for the whole graph.

        Args:
            x (torch.Tensor, [n x d]): tensor of node features from the entire graph
            edge_index (torch.Tensor, [2 x m]): edge index of entire graph
            num_nodes (int, optional): number of nodes in graph

        Returns:
            exp (dict):
                exp['feature_imp'] (torch.Tensor, [d]): feature mask explanation
                exp['edge_imp'] (torch.Tensor, [m]): k-hop edge importance
                exp['node_imp'] (torch.Tensor, [m]): k-hop node importance
        """
        exp = {k: None for k in EXP_TYPES}

        n = maybe_num_nodes(edge_index, None) if num_nodes is None else num_nodes
        rand_mask = torch.bernoulli(0.5 * torch.ones(n, 1))
        exp['feature_imp'] = rand_mask * torch.randn_like(x)

        exp['edge_imp'] = torch.randn(edge_index[0, :].shape)

        return exp

    def get_explanation_link(self):
        """
        Explain a link prediction.
        """
        raise NotImplementedError()
