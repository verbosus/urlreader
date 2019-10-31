import setuptools


with open("README.md", "r") as fh:
    long_description = fh.read()


setuptools.setup(
    name="urlreader",
    version="0.1.3",
    author="Antonio Cavedoni",
    author_email="antonio@cavedoni.org",
    description="URLReader: a wrapper around macOS’s NSURLSession, etc. for PyObjC apps",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/verbosus/urlreader",
    packages=setuptools.find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: MacOS :: MacOS X",
        "Development Status :: 3 - Alpha",
        "Environment :: MacOS X",
        "Environment :: MacOS X :: Cocoa",
        "Topic :: Internet",
    ],
    python_requires='>=3.6',
    install_requires=[
        'pyobjc>=5.2'
    ],
    test_suite="tests",
)
