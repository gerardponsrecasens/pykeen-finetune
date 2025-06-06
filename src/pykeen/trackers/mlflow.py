"""An adapter for MLflow."""

from collections.abc import Mapping
from typing import Any

from .base import ResultTracker
from ..utils import flatten_dictionary

__all__ = [
    "MLFlowResultTracker",
]


class MLFlowResultTracker(ResultTracker):
    """A tracker for MLflow."""

    def __init__(
        self,
        tracking_uri: str | None = None,
        experiment_id: int | None = None,
        experiment_name: str | None = None,
        tags: dict[str, Any] | None = None,
    ):
        """Initialize result tracking via MLFlow.

        :param tracking_uri: The tracking uri.
        :param experiment_id: The experiment ID. If given, this has to be the ID of an existing experiment in MFLow. Has
            priority over experiment_name.
        :param experiment_name: The experiment name. If this experiment name exists, add the current run to this
            experiment. Otherwise create an experiment of the given name.
        :param tags: The additional run details which are presented as tags to be logged
        """
        import mlflow as _mlflow

        self.mlflow = _mlflow
        self.tags = tags

        self.mlflow.set_tracking_uri(tracking_uri)
        if experiment_id is not None:
            experiment = self.mlflow.get_experiment(experiment_id=experiment_id)
            experiment_name = experiment.name
        if experiment_name is not None:
            self.mlflow.set_experiment(experiment_name)

    # docstr-coverage: inherited
    def start_run(self, run_name: str | None = None) -> None:  # noqa: D102
        self.mlflow.start_run(run_name=run_name)
        if self.tags is not None:
            self.mlflow.set_tags(tags=self.tags)

    # docstr-coverage: inherited
    def log_metrics(
        self,
        metrics: Mapping[str, float],
        step: int | None = None,
        prefix: str | None = None,
    ) -> None:  # noqa: D102
        metrics = flatten_dictionary(dictionary=metrics, prefix=prefix)
        self.mlflow.log_metrics(metrics=metrics, step=step)

    # docstr-coverage: inherited
    def log_params(self, params: Mapping[str, Any], prefix: str | None = None) -> None:  # noqa: D102
        params = flatten_dictionary(dictionary=params, prefix=prefix)
        self.mlflow.log_params(params=params)

    # docstr-coverage: inherited
    def end_run(self, success: bool = True) -> None:  # noqa: D102
        status = self.mlflow.entities.RunStatus.FINISHED if success else self.mlflow.entities.RunStatus.FAILED
        self.mlflow.end_run(status=self.mlflow.entities.RunStatus.to_string(status))
