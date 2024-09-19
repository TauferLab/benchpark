from spack import *


class A4xBenchmark(CachedCMakePackage):
    
    homepage = "https://analytics4md.org/"
    git      = "git@github.com:Analytics4MD/a4x-benchmark.git"

    maintainers("ilumsden")
    
    version("main", branch="main")
    version("summary_print", branch="summary_print")
    version("expanded_perf", branch="expanded_perf")
    version("0.1.0", tag="v0.1.0")
    
    core_plugins_values = ("mpi", "filesystem", "dyad")
    variant("core_plugins", default="mpi,filesystem", values=core_plugins_values, multi=True)
    variant("caliper", default=False)
    
    depends_on("mpi", type=("build", "link"))
    depends_on("nlohmann-json", type="link")
    depends_on("fmt", type="link")
    depends_on("a4x-core", type="link")
    depends_on("a4x-orchestration", type="link")
    depends_on("a4x-orchestration@explicit_sync_hooks", when="@summary_print", type="link")
    depends_on("caliper", when="@summary_print", type=("build", "link", "run"))
    depends_on("adiak", when="@summary_print", type="link")

    depends_on("a4x-core +caliper", when="+caliper")
    
    # Use a for loop here since there's currently no way to easily propagate
    # a4md-benchmark's core_plugins variant to a4md-core's plugins variant
    for cpv in core_plugins_values:
        depends_on("a4x-core plugins={}".format(cpv), when="core_plugins={}".format(cpv))


    def initconfig_package_entries(self):
        entries = super(A4xBenchmark, self).initconfig_package_entries()
        if not self.spec.satisfies("@summary_print") and self.spec.satisfies("+caliper"):
            entries.append(cmake_cache_string("A4X_PROFILER", "CALIPER"))
        return entries
    
