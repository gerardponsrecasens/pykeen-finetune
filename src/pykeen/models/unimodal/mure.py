"""Implementation of MuRE."""

from collections.abc import Mapping
from typing import Any, ClassVar

from torch.nn.init import normal_, uniform_, zeros_

from ..nbase import ERModel
from ...constants import DEFAULT_EMBEDDING_HPO_EMBEDDING_DIM_RANGE
from ...nn.modules import MuREInteraction
from ...typing import FloatTensor, Hint, Initializer

__all__ = [
    "MuRE",
]


class MuRE(ERModel[tuple[FloatTensor, FloatTensor], tuple[FloatTensor, FloatTensor], tuple[FloatTensor, FloatTensor]]):
    r"""An implementation of MuRE from [balazevic2019b]_.

    This model represents entities as $d$-dimensional vectors, and relations by two $k$-dimensional vectors.
    Moreover, there are separate scalar biases for each entity and each role (head or tail).
    All representations are stored in :class:`~pykeen.nn.representation.Embedding` matrices.

    The :class:`~pykeen.nn.modules.MuREInteraction` function is used to obtain scores.

    ---
    citation:
        author: Balažević
        year: 2019
        link: https://arxiv.org/abs/1905.09791
    """

    #: The default strategy for optimizing the model's hyper-parameters
    hpo_default: ClassVar[Mapping[str, Any]] = dict(
        embedding_dim=DEFAULT_EMBEDDING_HPO_EMBEDDING_DIM_RANGE,
        p=dict(type=int, low=1, high=2),
    )

    def __init__(
        self,
        *,
        embedding_dim: int = 200,
        p: int = 2,
        power_norm: bool = True,
        entity_initializer: Hint[Initializer] = normal_,
        entity_initializer_kwargs: Mapping[str, Any] | None = None,
        entity_bias_initializer: Hint[Initializer] = zeros_,
        relation_initializer: Hint[Initializer] = normal_,
        relation_initializer_kwargs: Mapping[str, Any] | None = None,
        relation_matrix_initializer: Hint[Initializer] = uniform_,
        relation_matrix_initializer_kwargs: Mapping[str, Any] | None = None,
        **kwargs,
    ) -> None:
        r"""Initialize MuRE via the :class:`pykeen.nn.modules.MuREInteraction` interaction.

        :param embedding_dim: The entity embedding dimension $d$. Defaults to 200. Is usually $d \in [50, 300]$.

        :param p:
            The norm used with :func:`torch.linalg.vector_norm`. Typically is 1 or 2.
        :param power_norm:
            Whether to use the p-th power of the $L_p$ norm. It has the advantage of being differentiable around 0,
            and numerically more stable.

        :param entity_initializer: Entity initializer function. Defaults to :func:`torch.nn.init.normal_`
        :param entity_initializer_kwargs: Keyword arguments to be used when calling the entity initializer

        :param entity_bias_initializer: Entity bias initializer function. Defaults to :func:`torch.nn.init.zeros_`

        :param relation_initializer: Relation initializer function. Defaults to :func:`torch.nn.init.normal_`
        :param relation_initializer_kwargs: Keyword arguments to be used when calling the relation initializer

        :param relation_matrix_initializer: Relation matrix initializer function.
            Defaults to :func:`torch.nn.init.uniform_`
        :param relation_matrix_initializer_kwargs: Keyword arguments to be used when calling the
            relation matrix initializer

        :param kwargs: Remaining keyword arguments passed through to :class:`~pykeen.models.ERModel`.
        """
        # comment:
        # https://github.com/ibalazevic/multirelational-poincare/blob/34523a61ca7867591fd645bfb0c0807246c08660/model.py#L52
        # uses float64
        super().__init__(
            interaction=MuREInteraction,
            interaction_kwargs=dict(p=p, power_norm=power_norm),
            entity_representations_kwargs=[
                dict(
                    shape=embedding_dim,
                    initializer=entity_initializer,
                    initializer_kwargs=entity_initializer_kwargs or dict(std=1.0e-03),
                ),
                # entity bias for head
                dict(
                    shape=tuple(),  # scalar
                    initializer=entity_bias_initializer,
                ),
                # entity bias for tail
                dict(
                    shape=tuple(),  # scalar
                    initializer=entity_bias_initializer,
                ),
            ],
            relation_representations_kwargs=[
                # relation offset
                dict(
                    shape=embedding_dim,
                    initializer=relation_initializer,
                    initializer_kwargs=relation_initializer_kwargs
                    or dict(
                        std=1.0e-03,
                    ),
                ),
                # diagonal relation transformation matrix
                dict(
                    shape=embedding_dim,
                    initializer=relation_matrix_initializer,
                    initializer_kwargs=relation_matrix_initializer_kwargs or dict(a=-1, b=1),
                ),
            ],
            **kwargs,
        )
