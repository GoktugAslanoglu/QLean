from transformers import PreTrainedConfig


class QLeanConfig(PreTrainedConfig):
    model_type = "qlean_overlay"

    def __init__(self, base_model=None, base_revision=None, overlay="identity", **kwargs):
        super().__init__(**kwargs)
        self.base_model = base_model
        self.base_revision = base_revision
        self.overlay = overlay
