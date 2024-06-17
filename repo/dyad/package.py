from spack import *


class Dyad(CachedCMakePackage, AutotoolsPackage):

    homepage = "https://dyad.readthedocs.io"
    git      = "https://github.com/flux-framework/dyad.git"

    # TODO add new version once we pin the post-HiCOMB/SC version of DYAD
    version("main", branch="main")
    version("0.1.1", tag="v0.1.1", deprecated=True)
    version("0.1.0", tag="v0.1.0", deprecated=True)
    
    variant("ucx_tag", default=False)  # DYAD_ENABLE_UCX_DATA
    variant("ucx_rma", default=True)  # DYAD_ENABLE_UCX_DATA_RMA
    variant("caliper", default=False)  # DYAD_PROFILER=CALIPER
    variant("dftracer", default=False)  # DYAD_PROFILER=DLIO_PROFILER
    variant("logger", default="none", values=("flux", "cpp_logger", "none"))  # DYAD_LOGGER
    variant("log_level", default="none", values=("debug", "info", "warn", "error", "none"))  # DYAD_LOGGER_LEVEL
    
    depends_on("pkg-config", type="build")
    depends_on("flux-core", type=("build", "link", "run"))
    depends_on("jansson@2.10:", type="link")
    depends_on("cpp-logger", when="logger=cpp_logger", type="link")
    depends_on("py-dlio-profiler-py", when="+dftracer",  type="link")
    depends_on("caliper", when="+caliper", type="link")
    depends_on("ucx@1.6:", when="+ucx_tag", type="link")
    depends_on("ucx@1.6:", when="+ucx_rma", type="link")

    with when("build_system=autotools"):
        depends_on("autoconf", type="build")
        depends_on("automake", type="build")
        depends_on("libtool",  type="build")
        
    conflicts(
        "+ucx_tag",
        when="+ucx_rma",
        msg="Cannot build with both UCX tag-matching and UCX RMA"
    )
    
    build_system(
        # conditional("cmake", when="@0.2.0:"),
        conditional("cmake", when="@main"),
        conditional("autotools", when="@:0.1.1"),
        default="cmake"
    )
    
    def initconfig_package_entries(self):
        entries = super(Dyad, self).initconfig_package_entries()
        entries.append(cmake_cache_option("DYAD_ENABLE_UCX_DATA", self.spec.satisfies("+ucx_tag")))
        entries.append(cmake_cache_option("DYAD_ENABLE_UCX_DATA_RMA", self.spec.satisfies("+ucx_rma")))

        if self.spec.satisfies("+caliper"):
            entries.append(cmake_cache_string("DYAD_PROFILER", "CALIPER"))
        elif self.spec.satisfies("+dftracer"):
            entries.append(cmake_cache_string("DYAD_PROFILER", "DLIO_PROFILER"))
        else:
            entries.append(cmake_cache_string("DYAD_PROFILER", "NONE"))

        if self.spec.satisfies("logger=flux"):
            entries.append(cmake_cache_string("DYAD_LOGGER", "FLUX"))
        elif self.spec.satisfies("logger=cpp_logger"):
            entries.append(cmake_cache_string("DYAD_LOGGER", "CPP_LOGGER"))
        else:
            entries.append(cmake_cache_string("DYAD_LOGGER", "NONE"))

        if self.spec.satisfies("log_level=debug"):
            entries.append(cmake_cache_string("DYAD_LOGGER_LEVEL", "DEBUG"))
        elif self.spec.satisfies("log_level=info"):
            entries.append(cmake_cache_string("DYAD_LOGGER_LEVEL", "INFO"))
        elif self.spec.satisfies("log_level=warn"):
            entries.append(cmake_cache_string("DYAD_LOGGER_LEVEL", "WARN"))
        elif self.spec.satisfies("log_level=error"):
            entries.append(cmake_cache_string("DYAD_LOGGER_LEVEL", "ERROR"))
        else:
            entries.append(cmake_cache_string("DYAD_LOGGER_LEVEL", "NONE"))

        return entries
