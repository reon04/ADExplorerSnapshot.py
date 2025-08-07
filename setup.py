from setuptools import setup
import site, sys

site.ENABLE_USER_SITE = "--user" in sys.argv[1:]

setup(name='ADExplorerSnapshot',
      version='1.2.0',
      description='ADExplorerSnapshot.py is an AD Explorer snapshot parser. It is made as an ingestor for BloodHound, and also supports full-object dumping to NDJSON.',
      author='David Micus',
      author_email='david.micus@secida.com',
      maintainer='David Micus',
      maintainer_email='david.micus@secida.com',
      url='https://github.com/reon04/ADExplorerSnapshot.py',
      packages=['adexpsnapshot',
                'adexpsnapshot.parser',
      ],
      license='MIT',
      install_requires=['bloodhound-ce>=1.8.0','dissect.cstruct>=2.0','frozendict','requests','pwntools>=4.5.0','certipy-ad>=5.0.2'],
      classifiers=[
        'Environment :: Console',
        'Intended Audience :: Information Technology',
        'Intended Audience :: Science/Research',
        'Intended Audience :: System Administrators',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Programming Language :: Python :: 3.12',
        'Programming Language :: Python :: 3.13',
        'Topic :: Security'
      ],
      entry_points= {
        'console_scripts': ['ADExplorerSnapshot.py=adexpsnapshot:main']
      },
      python_requires='>=3.8'
)
