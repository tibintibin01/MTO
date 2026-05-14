# -*- coding: utf-8 -*-
import pytest
import sys
import os

if __name__ == "__main__":
    print("MTO INDUSTRIAL TEST RUNNER")
    print("----------------------------")
    
    # Ensure project root is in path
    sys.path.append(os.path.abspath(os.path.dirname(__file__)))
    
    # Run pytest on the tests directory
    args = [
        "tests",
        "-v",
        "--tb=short"
    ]
    
    retcode = pytest.main(args)
    sys.exit(retcode)
