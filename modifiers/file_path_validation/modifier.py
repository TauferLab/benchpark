from ramble.modkit import *


class FilePathValidation(BasicModifier):
    
    name = "file_path_validator"
    
    tags("infrastructure")
    
    maintainers("ilumsden")
    
    mode("standard", description="Standard mode for validating file paths")
    default_mode("standard")
    
    