from spack import *


class A4mdCore(CachedCMakePackage):

    homepage = "https://analytics4md.org/"
    # TODO: change to HTTPS URL once repo is public
    git      = "git@github.com:Analytics4MD/a4md-core.git"
    
    # Note: may require enabling submodules in future (e.g., once Cereal is working)
    version("main", branch="main")
    
    variant("log_level", default="none",
            values=["none", "trace", "debug", "info", "warn", "error", "critical"])
    variant("caliper", default=False)
    variant("dyad", default=False)
    # TODO: uncomment once we get DSpaces working
    # variant("+dspaces", default=False)
    
    depends_on("mpi", type=("build", "link"))
    depends_on("nlohmann-json", type="link")
    depends_on("fmt", type="link")
    depends_on("spdlog", type="link")
    
    # TODO: change to specific minimum version once next release of DYAD is pinned
    depends_on("dyad@main", when="+dyad", type=("link", "run"))
    # TODO: uncomment once we get DSpaces working
    # depends_on("dspaces@2.2", when="+dspaces")
    depends_on("caliper", when="+caliper", type="link")
    

    def initconfig_package_entries(self):
        entries = super(A4mdCore, self).initconfig_package_entries()
        entries.append(cmake_cache_option("DTL_DYAD", self.spec.satisfies("+dyad")))
        entries.append(cmake_cache_option("DTL_DSPACES", self.spec.satisfies("+dspaces")))
        
        if self.spec.satisfies("+caliper"):
            entries.append(cmake_cache_option("ENABLE_PERF", True))
            entries.append(cmake_cache_option("A4MD_PERF_PLUGIN", "CALIPER"))
        else:
            entries.append(cmake_cache_option("ENABLE_PERF", False))
            
        if self.spec.satisfies("log_level=critical"):
            entries.append(cmake_cache_option("A4MD_LOG_LEVEL", "CRITICAL"))
        elif self.spec.satisfies("log_level=error"):
            entries.append(cmake_cache_option("A4MD_LOG_LEVEL", "ERROR"))
        elif self.spec.satisfies("log_level=warn"):
            entries.append(cmake_cache_option("A4MD_LOG_LEVEL", "WARN"))
        elif self.spec.satisfies("log_level=info"):
            entries.append(cmake_cache_option("A4MD_LOG_LEVEL", "INFO"))
        elif self.spec.satisfies("log_level=debug"):
            entries.append(cmake_cache_option("A4MD_LOG_LEVEL", "DEBUG"))
        elif self.spec.satisfies("log_level=trace"):
            entries.append(cmake_cache_option("A4MD_LOG_LEVEL", "TRACE"))
        else:
            entries.append(cmake_cache_option("A4MD_LOG_LEVEL", "NONE"))
            
        return entries