class FeatureNotImplemented(NotImplementedError):
    """An explicit template boundary, never a simulated successful result."""
    def __init__(self, operation: str):
        self.operation = operation
        super().__init__(f'{operation} is not implemented in this template')
