from spack import *


class A4mdBenchmark(CachedCMakePackage):
    
    homepage = "https://analytics4md.org/"
    git      = "git@github.com:Analytics4MD/a4md-benchmark.git"
    
    version("main", branch="main")
    
    variant("caliper", default=False)
    variant("dyad", default=False)
    
    depends_on("mpi", type=("build", "link"))
    depends_on("nlohmann-json", type="link")
    depends_on("fmt", type="link")
    depends_on("cli11", type="link")
    depends_on("a4md-core@main", type="link")
    depends_on("a4md-orchestration@main log_level=none", type="link")
    
    depends_on("a4md-core@main +dyad", when="+dyad")
    depends_on("a4md-core@main +caliper", when="+caliper")
    