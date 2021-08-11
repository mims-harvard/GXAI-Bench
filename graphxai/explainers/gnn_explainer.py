import numpy as np
import torch

from typing import Optional
from torch_geometric.utils import k_hop_subgraph

from graphxai.explainers._base import _BaseExplainer
from graphxai.utils.constants import EXP_TYPES


class GNNExplainer(_BaseExplainer):
    """
    GNNExplainer: node only
    """
    def __init__(self, model, coeff=None):
        """
        Args:
            model (torch.nn.Module): model on which to make predictions
                The output of the model should be unnormalized class score.
                For example, last layer = CNConv or Linear.
            coeff (dict, optional): coefficient of the entropy term and the size term
                for learning edge mask and node feature mask
                Default setting:
                    coeff = {'edge': {'entropy': 1.0, 'size': 0.005},
                             'feature': {'entropy': 0.1, 'size': 1.0}}
        """
        super().__init__(model)
        if coeff is not None:
            self.coeff = coeff
        else:
            self.coeff = {'edge': {'entropy': 1.0, 'size': 0.005},
                          'feature': {'entropy': 0.1, 'size': 1.0}}

    def get_explanation_node(self, node_idx: int, edge_index: torch.Tensor,
                             x: torch.Tensor, label: Optional[torch.Tensor] = None,
                             num_hops: Optional[int] = None,
                             get_feature_mask: bool = False,
                             forward_kwargs: dict = {}):
        """
        Explain a node prediction.

        Args:
            node_idx (int): index of the node to be explained
            edge_index (torch.Tensor, [2 x m]): edge index of the graph
            x (torch.Tensor, [n x d]): node features
            label (torch.Tensor, optional, [n x ...]): labels to explain
                If not provided, we use the output of the model.
            num_hops (int, optional): number of hops to consider
                If not provided, we use the number of graph layers of the GNN.
            get_feature_mask (bool): whether to compute the feature mask or not
            forward_kwargs (dict, optional): additional arguments to model.forward
                beyond x and edge_index

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
        label = self._predict(x, edge_index,
                              forward_kwargs=forward_kwargs) if label is None else label
        num_hops = self.L if num_hops is None else num_hops

        exp = {k: None for k in EXP_TYPES}

        khop_info = subset, sub_edge_index, mapping, _ = \
            k_hop_subgraph(node_idx, num_hops, edge_index,
                           relabel_nodes=True, num_nodes=x.shape[0])
        sub_x = x[subset]

        self._set_masks(sub_x, sub_edge_index, get_feature_mask=get_feature_mask)

        self.model.eval()
        num_epochs = 200

        # Loss function for GNNExplainer's objective
        def loss_fn(log_prob, mask, mask_type):
            # Select the log prob and the label of node_idx
            node_log_prob = log_prob[torch.where(subset==node_idx)].squeeze()
            node_label = label[mapping]
            # Maximize the probability of predicting the label (cross entropy)
            loss = -node_log_prob[node_label].item()
            a = mask.sigmoid()
            # Size regularization
            loss += self.coeff[mask_type]['size'] * torch.sum(a)
            # Element-wise entropy regularization
            # Low entropy implies the mask is close to binary
            entropy = -a * torch.log(a + 1e-15) - (1-a) * torch.log(1-a + 1e-15)
            loss += self.coeff[mask_type]['entropy'] * entropy.mean()
            return loss

        def train(mask, mask_type):
            optimizer = torch.optim.Adam([mask], lr=0.01)
            for epoch in range(1, num_epochs+1):
                optimizer.zero_grad()
                if mask_type == 'feature':
                    h = sub_x * mask.view(1, -1).sigmoid()
                else:
                    h = sub_x
                log_prob = self._predict(h, sub_edge_index, return_type='log_prob')
                loss = loss_fn(log_prob, mask, mask_type)
                loss.backward()
                optimizer.step()

        if explain_feature:
            train(self.feature_mask, 'feature')
            exp['feature_imp'] = self.feature_mask.data

        train(self.edge_mask, 'edge')
        exp['edge_imp'] = self.edge_mask.data

        self._clear_masks()

        return exp, khop_info

    def get_explanation_graph(self, edge_index: torch.Tensor,
                              x: torch.Tensor, label: torch.Tensor,
                              forward_kwargs: dict = None, explain_feature: bool = False):
        """
        Explain a whole-graph prediction.

        Args:
            edge_index (torch.Tensor, [2 x m]): edge index of the graph
            x (torch.Tensor, [n x d]): node features
            label (torch.Tensor, [n x ...]): labels to explain
            forward_kwargs (dict, optional): additional arguments to model.forward
                beyond x and edge_index
            explain_feature (bool): whether to explain the feature or not

        Returns:
            exp (dict):
                exp['feature_imp'] (torch.Tensor, [d]): feature mask explanation
                exp['edge_imp'] (torch.Tensor, [m]): k-hop edge importance
                exp['node_imp'] (torch.Tensor, [m]): k-hop node importance
        """
        raise Exception('GNNExplainer does not support graph-level explanation.') 

    def get_explanation_link(self):
        """
        Explain a link prediction.
        """
        raise NotImplementedError()
