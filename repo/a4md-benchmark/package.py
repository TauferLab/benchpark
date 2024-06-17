from spack import *


class A4mdBenchmark(CachedCmakePackage):
    
    homepage = "https://analytics4md.org/"
    git      = "git@github.com:Analytics4MD/a4md-benchmark.git"
    
    version("main", branch="main")
    
    depends_on("mpi", type=("build", "link"))
    depends_on("nlohmann-json", type="link")
    depends_on("fmt", type="link")
    depends_on("cli11", type="link")
    depends_on("a4md-core@main", type="link")
    depends_on("a4md-orchestration@main", type="link")
    