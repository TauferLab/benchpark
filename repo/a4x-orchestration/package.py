from spack import *


class A4xOrchestration(CachedCMakePackage):

    homepage = "https://analytics4md.org/"
    # TODO: change to HTTPS URL once repo is public
    git      = "git@github.com:Analytics4MD/a4x-orchestration.git"
    
    version("main", branch="main")
    
    depends_on("mpi", type=("build", "link"))
    depends_on("nlohmann-json", type="link")
    