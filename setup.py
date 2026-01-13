from setuptools import setup

setup(
    name="OctoPrint-ReconnectGuru",
    version="0.0.4",
    description="Automatically reconnects to printers detected via udev events",
    long_description=(
        "An OctoPrint plugin that monitors udev events for USB device connections "
        "and automatically connects OctoPrint to matching printers based on "
        "configurable filters (vendor ID, product ID, serial number, USB port)."
    ),
    long_description_content_type="text/plain",
    author="Ed Cragg",
    url="https://github.com/nuxeh/OctoPrint-ReconnectGuru",
    license="ISC",
    python_requires=">=3.7,<4",
    packages=["octoprint_reconnect_guru"],
    include_package_data=True,
    install_requires=[
        "pyudev>=0.22",
        "pyserial>=3.4",
    ],
    entry_points={
        "octoprint.plugin": [
            "reconnect_guru = octoprint_reconnect_guru"
        ]
    },
    zip_safe=False,
)
