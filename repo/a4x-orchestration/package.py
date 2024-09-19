from spack import *


class A4xOrchestration(CachedCMakePackage):

    homepage = "https://analytics4md.org/"
    # TODO: change to HTTPS URL once repo is public
    git      = "git@github.com:Analytics4MD/a4x-orchestration.git"

    maintainers("ilumsden")
    
    version("main", branch="main")
    version("explicit_sync_hooks", branch="explicit_sync_hooks")
    version("0.1.0", tag="v0.1.0")
    
    depends_on("mpi", type=("build", "link"))
    depends_on("nlohmann-json", type="link")
    
