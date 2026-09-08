import sys, os
sys.path.insert(0, os.environ["PLUGIN_DIR"])
import pytest
sys.exit(int(pytest.main(sys.argv[1:] + ["-q", "-rA", "-m", "not slow", "-p", "no:cacheprovider", "-p", "timing_capture"])))
