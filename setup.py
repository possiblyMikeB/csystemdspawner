from setuptools import setup

setup(
    name='csystemdspawner',
    version='git',
    description='JupyterHub Spawner using systemd for resource allocation, isolation, and remote spawning',
    long_description='See https://github.com/possiblyMikeB/csystemdspawner for more info',
    url='https://github.com/possibleMikeB/csystemdspawner',
    author='Michael Blackmon',
    author_email='miblackmon@davidson.edu',
    license='3 Clause BSD',
    packages=['csystemdspawner'],
    entry_points={
        'jupyterhub.spawners': [
            'csystemdspawner = csystemdspawner:CSystemdSpawner',
        ],
    },
    install_requires=[
        'jupyterhub>=0.9',
        'tornado>=5.0'
    ],
)
