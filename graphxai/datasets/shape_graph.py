import torch
import random
import numpy as np
import networkx as nx
import matplotlib.pyplot as plt
from types import MethodType
from typing import Optional, Callable, Union
from functools import partial
from torch_geometric.utils import k_hop_subgraph, to_undirected
from torch_geometric.data import Data

from graphxai.utils.nx_conversion import khop_subgraph_nx
from graphxai import Explanation
from graphxai.datasets.utils.shapes import *
from graphxai.datasets.dataset import NodeDataset, GraphDataset
from graphxai.datasets.feature import make_structured_feature
from graphxai.datasets.utils.bound_graph import build_bound_graph as BBG_old
from graphxai.datasets.utils.bound_graph_pref_att import build_bound_graph as BBG_PA
from graphxai.datasets.utils.verify import verify_motifs

from graphxai.datasets.utils.feature_generators import gaussian_lv_generator
from graphxai.datasets.utils.label_generators import bound_graph_label

class ShapeGraph(NodeDataset):
    '''
    BA Shapes dataset with keyword arguments for different planting, 
        insertion, labeling, and feature generation methods

    ..note:: Flag and circle shapes not yet implemented

    Args:
        model_layers (int, optional): Number of layers within the GNN that will
            be explained. This defines the extent of the ground-truth explanations
            that are created by the method. (:default: :obj:`3`)
        shape (str, optional): Type of shape to be inserted into graph.
            Options are `'house'`, `'flag'`, `'circle'`, and `'multiple'`. 
            If `'multiple'`, random shapes are generated to insert into 
            the graph.
            (:default: :obj:`'house'`)
        seed (int, optional): Seed for graph generation. (:default: `None`)

        TODO: Ensure seed keeps graph generation constant.

        kwargs: Additional arguments
            variant (int): 0 indicates using the old ShapeGraph method, and 1 indicates
                using the new ShapeGraph method (i.e. one with pref. attachment).   
            num_subgraphs (int): Number of individual subgraphs to use in order to build
                the graph. Doesn't guarantee size of graph. (:default: :obj:`10`)
            prob_connection (float): Probability of making a connection between any two
                of the original subgraphs. Roughly controls sparsity and number of 
                class 0 vs. class 1 nodes. (:default: :obj:`1`)
            subgraph_size (int): Expected size of each individual subgraph.
            base_graph (str): Base graph structure to use for generating subgraphs.
                Only in effect for variant 0. (:default: :obj:`'ba'`)
            verify (bool): Verifies that graph does not have any "bad" motifs in it.
                (:default: :obj:`True`)
            max_tries_verification (int): Maximum number of tries to re-generate a 
                graph that contains bad motifs. (:default: :obj:`5`)
            
    Members:
        G (nx.Graph): Networkx version of the graph for the dataset
            - Contains many values per-node: 
                1. 'shape': which motif a given node is within
                2. 'shapes_in_khop': number of motifs within a (num_hops)-
                    hop neighborhood of the given node.
                    - Note: only for bound graph
    '''

    def __init__(self,  
        model_layers: int = 3,
        shape: Union[str, nx.Graph] = 'house',
        seed: Optional[int] = None,
        make_explanations: Optional[bool] = True,
        **kwargs): # TODO: turn the last three arguments into kwargs

        super().__init__(name = 'ShapeGraph', num_hops = model_layers)

        self.in_shape = []
        self.graph = None
        self.model_layers = model_layers
        self.make_explanations = make_explanations

        # Parse kwargs:
        self.variant = 1 if 'variant' not in kwargs else kwargs['variant']
            # 0 is old, 1 is preferential attachment one
        self.num_subgraphs = 10 if 'num_subgraphs' not in kwargs else kwargs['num_subgraphs']
        self.prob_connection = 1 if 'prob_connection' not in kwargs else kwargs['prob_connection']
        self.subgraph_size = 13 if 'subgraph_size' not in kwargs else kwargs['subgraph_size']
        self.base_graph = 'ba' if 'base_graph' not in kwargs else kwargs['base_graph']
        self.verify = True if 'verify' not in kwargs else kwargs['verify']
        self.max_tries_verification = 5 if 'max_tries_verification' not in kwargs else kwargs['max_tries_verification']

        #self.flip_y = 0.01 if 'flip_y' not in kwargs else kwargs['flip_y']
        self.n_informative = 4 if 'n_informative' not in kwargs else kwargs['n_informative']
        self.class_sep = 1.0 if 'class_sep' not in kwargs else kwargs['class_sep']
        self.n_features = 10 if 'n_features' not in kwargs else kwargs['n_features']
        self.n_clusters_per_class = 2 if 'n_clusters_per_class' not in kwargs else kwargs['n_clusters_per_class']

        self.add_sensitive_feature = True if 'add_sensitive_feature' not in kwargs else kwargs['add_sensitive_feature']

        self.seed = seed

        # Get shape:
        self.shape_method = ''
        if isinstance(shape, nx.Graph):
            self.insert_shape = shape
        else:
            self.insert_shape = None
            shape = shape.lower()
            self.shape_method = shape
            if shape == 'house':
                self.insert_shape = house
            elif shape == 'flag':
                pass
            elif shape == 'circle':
                self.insert_shape = pentagon # 5-member ring

            # if shape == 'random':
            #     # random_shape imported from utils.shapes
            #     self.get_shape = partial(random_shape, n=3) 
            #     # Currenlty only support for 3-member shape bank (n=3)
            # else:
            #     def tmp():
            #         return self.insert_shape, 1
            #     self.get_shape = tmp

            assert shape != 'random', 'Multiple shapes not yet supported for bounded graph'

        # Build graph:

        if self.verify and shape != 'random':
            for i in range(self.max_tries_verification):
                if self.variant == 0:
                    self.G = BBG_old(
                        shape = self.insert_shape, 
                        num_subgraphs = self.num_subgraphs, 
                        inter_sg_connections = 1,
                        prob_connection = self.prob_connection,
                        subgraph_size = self.subgraph_size,
                        num_hops = 1,
                        base_graph = self.base_graph,
                        seed = self.seed,
                        )

                elif self.variant == 1:
                    self.G = BBG_PA(
                        shape = self.insert_shape, 
                        num_subgraphs = self.num_subgraphs, 
                        inter_sg_connections = 1,
                        prob_connection = self.prob_connection,
                        subgraph_size = self.subgraph_size,
                        num_hops = 1,
                        seed = self.seed
                        )

                if verify_motifs(self.G, self.insert_shape):
                    # If the motif verification passes
                    break
            else:
                # Raise error if we couldn't generate a valid graph
                raise RuntimeError(f'Could not build a valid graph in {self.max_tries_verification} attempts. \
                    \n Try using different parameters for graph generation or increasing max_tries_verification argument value.')
            
        else:
            if self.variant == 0:
                self.G = BBG_old(
                        shape = self.insert_shape, 
                        num_subgraphs = self.num_subgraphs, 
                        inter_sg_connections = 1,
                        prob_connection = self.prob_connection,
                        subgraph_size = self.subgraph_size,
                        num_hops = 1,
                        base_graph = self.base_graph,
                        seed = self.seed,
                        )
            elif self.variant == 1:
                self.G = BBG_PA(
                    shape = self.insert_shape, 
                    num_subgraphs = self.num_subgraphs, 
                    inter_sg_connections = 1,
                    prob_connection = self.prob_connection,
                    subgraph_size = self.subgraph_size,
                    num_hops = 1,
                    seed = self.seed
                    )


        self.generate_shape_graph() # Performs planting, augmenting, etc.
        self.num_nodes = self.G.number_of_nodes() # Number of nodes in graph

        # Set random splits for size n graph:
        range_set = list(range(self.num_nodes))
        random.seed(1234) # Seed random before making splits
        train_nodes = random.sample(range_set, int(self.num_nodes * 0.7))
        test_nodes  = random.sample(range_set, int(self.num_nodes * 0.25))
        valid_nodes = random.sample(range_set, int(self.num_nodes * 0.05))

        self.fixed_train_mask = torch.tensor([s in train_nodes for s in range_set], dtype=torch.bool)
        self.fixed_test_mask = torch.tensor([s in test_nodes for s in range_set], dtype=torch.bool)
        self.fixed_valid_mask = torch.tensor([s in valid_nodes for s in range_set], dtype=torch.bool)

    def generate_shape_graph(self):
        '''
        Generates the full graph with the given insertion and planting policies.

        :rtype: :obj:`torch_geometric.Data`
        Returns:
            data (torch_geometric.Data): Entire generated graph.
        '''

        gen_labels = bound_graph_label(self.G)
        y = torch.tensor([gen_labels(i) for i in self.G.nodes], dtype=torch.long)
        self.yvals = y.detach().clone() # MUST COPY TO AVOID MAJOR BUGS

        gen_features, self.feature_imp_true = gaussian_lv_generator(
            self.G, self.yvals, seed = self.seed,
            n_features = self.n_features,
            class_sep = self.class_sep,
            n_informative = self.n_informative,
            n_clusters_per_class=self.n_clusters_per_class,
        )
        x = torch.stack([gen_features(i) for i in self.G.nodes]).float()

        if self.add_sensitive_feature:
            sensitive = torch.randint(low=0, high=2, size = (x.shape[0],)).float()

            # Add sensitive attribute to last dimension on x
            x = torch.cat([x, sensitive.unsqueeze(1)], dim = 1)
            # Expand feature importance and mark last dimension as negative
            self.feature_imp_true = torch.cat([self.feature_imp_true, torch.zeros((1,))])

            # Shuffle to mix in x:
            shuffle_ind = torch.randperm(x.shape[1])
            x[:,shuffle_ind] = x.clone()
            self.feature_imp_true[shuffle_ind] = self.feature_imp_true.clone()

            # Sensitive feature is in the location where the last index was:
            self.sensitive_feature = shuffle_ind[-1].item()

        else:
            self.sensitive_feature = None

        for i in self.G.nodes:
            self.G.nodes[i]['x'] = gen_features(i)

        edge_index = to_undirected(torch.tensor(list(self.G.edges), dtype=torch.long).t().contiguous())

        self.graph = Data(
            x=x, 
            y=y,
            edge_index = edge_index, 
            shape = torch.tensor(list(nx.get_node_attributes(self.G, 'shape').values()))
        )

        # Generate explanations:
        if self.make_explanations:
            self.explanations = [self.explanation_generator(n) for n in self.G.nodes]
        else:
            self.explanations = None

    def explanation_generator(self, node_idx):

        # Label node and edge imp based off of each node's proximity to a house

        # Find nodes in num_hops
        original_in_num_hop = set([self.G.nodes[n]['shape'] for n in khop_subgraph_nx(node_idx, 1, self.G) if self.G.nodes[n]['shape'] != 0])

        # Tag all nodes in houses in the neighborhood:
        khop_nodes = khop_subgraph_nx(node_idx, self.model_layers, self.G)
        node_imp_map = {i:(self.G.nodes[i]['shape'] in original_in_num_hop) for i in khop_nodes}
            # Make map between node importance in networkx and in pytorch data

        khop_info = k_hop_subgraph(
            node_idx,
            num_hops = self.model_layers,
            edge_index = to_undirected(self.graph.edge_index)
        )

        node_imp = torch.tensor([node_imp_map[i.item()] for i in khop_info[0]], dtype=torch.double)

        # Get edge importance based on edges between any two nodes in motif
        in_motif = khop_info[0][node_imp.bool()] # Get nodes in the motif
        edge_imp = torch.zeros(khop_info[1].shape[1], dtype=torch.double)
        for i in range(khop_info[1].shape[1]):
            # Highlight edge connecting two nodes in a motif
            if (khop_info[1][0,i] in in_motif) and (khop_info[1][1,i] in in_motif):
                edge_imp[i] = 1
                continue
            
            # Make sure that we highlight edges connecting to the source node if that
            #   node is not in a motif:
            one_edge_in_motif = ((khop_info[1][0,i] in in_motif) or (khop_info[1][1,i] in in_motif))
            node_idx_in_motif = (node_idx in in_motif)
            one_end_of_edge_is_nidx = ((khop_info[1][0,i] == node_idx) or (khop_info[1][1,i] == node_idx))

            if (one_edge_in_motif and one_end_of_edge_is_nidx) and (not node_idx_in_motif):
                edge_imp[i] = 1

        exp = Explanation(
            feature_imp=self.feature_imp_true,
            node_imp = node_imp,
            edge_imp = edge_imp,
            node_idx = node_idx
        )

        exp.set_enclosing_subgraph(khop_info)
        return exp


    def visualize(self, shape_label = False, ax = None, show = False):
        '''
        Args:
            shape_label (bool, optional): If `True`, labels each node according to whether
            it is a member of an inserted motif or not. If `False`, labels each node 
            according to its y-value. (:default: :obj:`True`)
        '''

        ax = ax if ax is not None else plt.gca()

        Gitems = list(self.G.nodes.items())
        node_map = {Gitems[i][0]:i for i in range(self.G.number_of_nodes())}

        if shape_label:
            y = [int(self.G.nodes[i]['shape'] > 0) for i in range(self.num_nodes)]
        else:
            ylist = self.graph.y.tolist()
            y = [ylist[node_map[i]] for i in self.G.nodes]

        node_weights = {i:node_map[i] for i in self.G.nodes}

        #pos = nx.kamada_kawai_layout(self.G)
        pos = nx.spring_layout(self.G, seed = 1234) # Seed to always be consistent in output
        #_, ax = plt.subplots()
        nx.draw(self.G, pos, node_color = y, labels = node_weights, ax=ax)
        #ax.set_title('ShapeGraph')
        #plt.tight_layout()

        if show:
            plt.show()