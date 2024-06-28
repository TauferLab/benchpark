from spack import *


class A4mdBenchmark(CachedCMakePackage):
    
    homepage = "https://analytics4md.org/"
    git      = "git@github.com:Analytics4MD/a4md-benchmark.git"
    
    version("main", branch="main")
    
    core_plugins_values = ("mpi", "filesystem", "dyad")
    variant("core_plugins", default="mpi,filesystem", values=core_plugins_values, multi=True)
    variant("caliper", default=False)
    
    depends_on("mpi", type=("build", "link"))
    depends_on("nlohmann-json", type="link")
    depends_on("fmt", type="link")
    depends_on("a4md-core@main log_level=none", type="link")
    depends_on("a4md-orchestration@main", type="link")

    depends_on("a4md-core +caliper", when="+caliper")
    
    # Use a for loop here since there's currently no way to easily propagate
    # a4md-benchmark's core_plugins variant to a4md-core's plugins variant
    for cpv in core_plugins_values:
        depends_on("a4md-core plugins={}".format(cpv), when="core_plugins={}".format(cpv))
    