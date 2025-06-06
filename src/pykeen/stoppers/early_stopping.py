"""Implementation of early stopping."""

import dataclasses
import logging
import math
import pathlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import torch

from .stopper import Stopper
from ..constants import PYKEEN_CHECKPOINTS
from ..evaluation import Evaluator
from ..models import Model
from ..trackers import ResultTracker
from ..triples import CoreTriplesFactory
from ..utils import fix_dataclass_init_docs

__all__ = [
    "is_improvement",
    "EarlyStopper",
    "EarlyStoppingLogic",
    "StopperCallback",
]

logger = logging.getLogger(__name__)

StopperCallback = Callable[[Stopper, int | float, int], None]


def is_improvement(
    best_value: float,
    current_value: float,
    larger_is_better: bool,
    relative_delta: float = 0.0,
) -> bool:
    """Decide whether the current value is an improvement over the best value.

    :param best_value: The best value so far.
    :param current_value: The current value.
    :param larger_is_better: Whether a larger value is better.
    :param relative_delta: A minimum relative improvement until it is considered as an improvement.

    :returns: Whether the current value is better.
    """
    better = current_value > best_value if larger_is_better else current_value < best_value
    return better and not math.isclose(current_value, best_value, rel_tol=relative_delta)


@dataclasses.dataclass
class EarlyStoppingLogic:
    """The early stopping logic."""

    #: the number of reported results with no improvement after which training will be stopped
    patience: int = 2

    # the minimum relative improvement necessary to consider it an improved result
    relative_delta: float = 0.0

    # whether a larger value is better, or a smaller.
    larger_is_better: bool = True

    #: The epoch at which the best result occurred
    best_epoch: int | None = None

    #: The best result so far
    best_metric: float = dataclasses.field(init=False)

    #: The remaining patience
    remaining_patience: int = dataclasses.field(init=False)

    def __post_init__(self):
        """Infer remaining default values."""
        self.remaining_patience = self.patience
        self.best_metric = float("-inf") if self.larger_is_better else float("+inf")

    def is_improvement(self, metric: float) -> bool:
        """Return if the given metric would cause an improvement."""
        return is_improvement(
            best_value=self.best_metric,
            current_value=metric,
            larger_is_better=self.larger_is_better,
            relative_delta=self.relative_delta,
        )

    def report_result(self, metric: float, epoch: int) -> bool:
        """Report a result at the given epoch.

        :param metric: The result metric.
        :param epoch: The epoch.

        :returns: If the result did not improve more than delta for patience evaluations

        :raises ValueError: if more than one metric is reported for a single epoch
        """
        if self.best_epoch is not None and epoch <= self.best_epoch:
            raise ValueError("Cannot report more than one metric for one epoch")

        # check for improvement
        if self.is_improvement(metric):
            self.best_epoch = epoch
            self.best_metric = metric
            self.remaining_patience = self.patience
        else:
            self.remaining_patience -= 1

        # stop if the result did not improve more than delta for patience evaluations
        return self.remaining_patience <= 0

    @property
    def is_best(self) -> bool:
        """Return whether the current result is the (new) best result."""
        return self.remaining_patience == self.patience


@fix_dataclass_init_docs
@dataclass
class EarlyStopper(Stopper):
    """A harness for early stopping."""

    #: The model
    model: Model = dataclasses.field(repr=False)
    #: The evaluator
    evaluator: Evaluator
    #: The triples to use for training (to be used during filtered evaluation)
    training_triples_factory: CoreTriplesFactory
    #: The triples to use for evaluation
    evaluation_triples_factory: CoreTriplesFactory
    #: Size of the evaluation batches
    evaluation_batch_size: int | None = None
    #: Slice size of the evaluation batches
    evaluation_slice_size: int | None = None
    #: The number of epochs after which the model is evaluated on validation set
    frequency: int = 10
    #: The number of iterations (one iteration can correspond to various epochs)
    #: with no improvement after which training will be stopped.
    patience: int = 2
    #: The name of the metric to use
    metric: str = "hits_at_k"
    #: The minimum relative improvement necessary to consider it an improved result
    relative_delta: float = 0.01
    #: The metric results from all evaluations
    results: list[float] = dataclasses.field(default_factory=list, repr=False)
    #: Whether a larger value is better, or a smaller
    larger_is_better: bool = True
    #: The result tracker
    result_tracker: ResultTracker | None = None
    #: Callbacks when after results are calculated
    result_callbacks: list[StopperCallback] = dataclasses.field(default_factory=list, repr=False)
    #: Callbacks when training gets continued
    continue_callbacks: list[StopperCallback] = dataclasses.field(default_factory=list, repr=False)
    #: Callbacks when training is stopped early
    stopped_callbacks: list[StopperCallback] = dataclasses.field(default_factory=list, repr=False)
    #: Did the stopper ever decide to stop?
    stopped: bool = False
    #: The path to the weights of the best model
    best_model_path: pathlib.Path | None = None
    #: Whether to delete the file with the best model weights after termination
    #: note: the weights will be re-loaded into the model before
    clean_up_checkpoint: bool = True
    #: Whether to use a tqdm progress bar for evaluation
    use_tqdm: bool = False
    #: Keyword arguments for the tqdm progress bar
    tqdm_kwargs: dict[str, Any] = dataclasses.field(default_factory=dict)

    _stopper: EarlyStoppingLogic = dataclasses.field(init=False, repr=False)

    def __post_init__(self):
        """Run after initialization and check the metric is valid."""
        # TODO: Fix this
        # if all(f.name != self.metric for f in dataclasses.fields(self.evaluator.__class__)):
        #     raise ValueError(f'Invalid metric name: {self.metric}')
        self._stopper = EarlyStoppingLogic(
            patience=self.patience,
            relative_delta=self.relative_delta,
            larger_is_better=self.larger_is_better,
        )
        if self.best_model_path is None:
            self.best_model_path = PYKEEN_CHECKPOINTS.joinpath(f"best-model-weights-{uuid4()}.pt")
            logger.info(f"Inferred checkpoint path for best model weights: {self.best_model_path}")
        if self.best_model_path.is_file():
            logger.warning(
                f"Checkpoint path for best weights does already exist ({self.best_model_path}). It will be overwritten."
            )

    @property
    def remaining_patience(self) -> int:
        """Return the remaining patience."""
        return self._stopper.remaining_patience

    @property
    def best_metric(self) -> float:
        """Return the best result so far."""
        return self._stopper.best_metric

    @property
    def best_epoch(self) -> int | None:
        """Return the epoch at which the best result occurred."""
        return self._stopper.best_epoch

    def should_evaluate(self, epoch: int) -> bool:
        """Decide if evaluation should be done based on the current epoch and the internal frequency."""
        return epoch > 0 and epoch % self.frequency == 0

    @property
    def number_results(self) -> int:
        """Count the number of results stored in the early stopper."""
        return len(self.results)

    def should_stop(self, epoch: int) -> bool:
        """Evaluate on a metric and compare to past evaluations to decide if training should stop."""
        # for mypy
        assert self.best_model_path is not None
        # Evaluate
        metric_results = self.evaluator.evaluate(
            model=self.model,
            additional_filter_triples=self.training_triples_factory.mapped_triples,
            mapped_triples=self.evaluation_triples_factory.mapped_triples,
            use_tqdm=self.use_tqdm,
            tqdm_kwargs=self.tqdm_kwargs,
            batch_size=self.evaluation_batch_size,
            slice_size=self.evaluation_slice_size,
            # Only perform time-consuming checks for the first call.
            do_time_consuming_checks=self.evaluation_batch_size is None,
        )
        # After the first evaluation pass the optimal batch and slice size is obtained and saved for re-use
        self.evaluation_batch_size = self.evaluator.batch_size
        self.evaluation_slice_size = self.evaluator.slice_size

        if self.result_tracker is not None:
            self.result_tracker.log_metrics(
                metrics=metric_results.to_flat_dict(),
                step=epoch,
                prefix="validation",
            )
        result = metric_results.get_metric(self.metric)

        # Append to history
        self.results.append(result)

        for result_callback in self.result_callbacks:
            result_callback(self, result, epoch)

        self.stopped = self._stopper.report_result(metric=result, epoch=epoch)
        if self.stopped:
            logger.info(
                f"Stopping early at epoch {epoch}. The best result {self.best_metric} occurred at "
                f"epoch {self.best_epoch}.",
            )
            for stopped_callback in self.stopped_callbacks:
                stopped_callback(self, result, epoch)
            logger.info(f"Re-loading weights from best epoch from {self.best_model_path}")
            self.model.load_state_dict(torch.load(self.best_model_path, weights_only=False))
            if self.clean_up_checkpoint:
                self.best_model_path.unlink()
                logger.debug(f"Clean up checkpoint with best weights: {self.best_model_path}")
            return True

        if self._stopper.is_best:
            torch.save(self.model.state_dict(), self.best_model_path)
            logger.info(
                f"New best result at epoch {epoch}: {self.best_metric}. Saved model weights to {self.best_model_path}",
            )

        for continue_callback in self.continue_callbacks:
            continue_callback(self, result, epoch)
        return False

    def get_summary_dict(self) -> Mapping[str, Any]:
        """Get a summary dict."""
        return dict(
            frequency=self.frequency,
            patience=self.patience,
            remaining_patience=self.remaining_patience,
            relative_delta=self.relative_delta,
            metric=self.metric,
            larger_is_better=self.larger_is_better,
            results=self.results,
            stopped=self.stopped,
            best_epoch=self.best_epoch,
            best_metric=self.best_metric,
        )

    def _write_from_summary_dict(
        self,
        *,
        frequency: int,
        patience: int,
        remaining_patience: int,
        relative_delta: float,
        metric: str,
        larger_is_better: bool,
        results: list[float],
        stopped: bool,
        best_epoch: int,
        best_metric: float,
    ) -> None:
        """Write attributes to stopper from a summary dict."""
        self.frequency = frequency
        self.patience = patience
        self.relative_delta = relative_delta
        self.metric = metric
        self.larger_is_better = larger_is_better
        self.results = results
        self.stopped = stopped
        # TODO need a test that this all re-instantiates properly
        self._stopper = EarlyStoppingLogic(
            patience=patience,
            relative_delta=relative_delta,
            larger_is_better=larger_is_better,
        )
        self._stopper.best_epoch = best_epoch
        self._stopper.best_metric = best_metric
        self._stopper.remaining_patience = remaining_patience
