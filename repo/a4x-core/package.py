from spack import *


class A4xCore(CachedCMakePackage):

    homepage = "https://analytics4md.org/"
    # TODO: change to HTTPS URL once repo is public
    git      = "git@github.com:Analytics4MD/a4x-core.git"
    
    # Note: may require enabling submodules in future (e.g., once Cereal is working)
    version("main", branch="main")
    
    variant("log_level", default="none",
            values=["none", "trace", "debug", "info", "warn", "error", "critical"])
    # TODO add dspaces to "values" once we get the DSpaces Plugin working
    variant("plugins", default="mpi,filesystem", values=("mpi", "filesystem", "dyad"), multi=True)
    variant("serializers", default="nlohmann", values=("nlohmann", "none"), multi=True)
    variant("caliper", default=False)
    
    depends_on("mpi", type=("build", "link"))
    depends_on("nlohmann-json", type="link")
    depends_on("fmt", type="link")
    depends_on("spdlog", type="link")
    
    # TODO: change to specific minimum version once next release of DYAD is pinned
    depends_on("dyad@main", when="plugins=dyad", type=("link", "run"))
    # TODO: uncomment once we get DSpaces working
    # depends_on("dspaces@2.2", when="+dspaces")
    depends_on("caliper", when="+caliper", type="link")
    

    def initconfig_package_entries(self):
        entries = super(A4mdCore, self).initconfig_package_entries()
        entries.append(cmake_cache_option("WITH_MPI_DTL", self.spec.satisfies("plugins=mpi")))
        entries.append(cmake_cache_option("WITH_FS_DTL", self.spec.satisfies("plugins=filesystem")))
        entries.append(cmake_cache_option("WITH_DYAD_DTL", self.spec.satisfies("plugins=dyad")))
        
        entries.append(cmake_cache_option("WITH_NLOHMANN_SERIALIZATION", self.spec.satisfies("serializers=nlohmann")))
        
        if self.spec.satisfies("+caliper"):
            entries.append(cmake_cache_string("A4MD_PROFILER", "CALIPER"))
            
        if self.spec.satisfies("log_level=critical"):
            entries.append(cmake_cache_string("A4MD_LOG_LEVEL", "CRITICAL"))
        elif self.spec.satisfies("log_level=error"):
            entries.append(cmake_cache_string("A4MD_LOG_LEVEL", "ERROR"))
        elif self.spec.satisfies("log_level=warn"):
            entries.append(cmake_cache_string("A4MD_LOG_LEVEL", "WARN"))
        elif self.spec.satisfies("log_level=info"):
            entries.append(cmake_cache_string("A4MD_LOG_LEVEL", "INFO"))
        elif self.spec.satisfies("log_level=debug"):
            entries.append(cmake_cache_string("A4MD_LOG_LEVEL", "DEBUG"))
        elif self.spec.satisfies("log_level=trace"):
            entries.append(cmake_cache_string("A4MD_LOG_LEVEL", "TRACE"))
        else:
            entries.append(cmake_cache_string("A4MD_LOG_LEVEL", "NONE"))
            
        return entries