import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def gryphon_home(tmp_path, monkeypatch):
    monkeypatch.setenv("GRYPHON_HOME", str(tmp_path / "home"))
    return tmp_path / "home"


@pytest.fixture()
def cfg():
    from gryphon_manager.core.config import MasterConfig
    return MasterConfig.load()


@pytest.fixture()
def repo():
    return REPO


def run_sim(cfg, seconds=20.0, base=1000.0, settings=None, **car_kw):
    from gryphon_manager.core.pipeline import Pipeline
    from gryphon_manager.core.simulator import SIM_DEVICES, SimCar
    car = SimCar(cfg, **car_kw)
    pipe = Pipeline(cfg, settings)
    pipe.engine.set_sim_devices(SIM_DEVICES)
    pipe.engine.mark_connected(base, True)
    pipe.run(car.step(0.0, seconds, base))
    return pipe.engine, car
