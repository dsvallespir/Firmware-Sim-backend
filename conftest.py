"""
conftest.py - Configuración global de pytest para el backend.

Desregistra plugins de ROS que interfieren con pytest cuando
el workspace tiene ROS/jazzy instalado en el sistema.
"""


def pytest_configure(config):
    """
    Desregistra el plugin launch_ros (launch_testing_ros_pytest_entrypoint)
    que registra hooks desconocidos ('pytest_launch_collect_makemodule')
    causando un PluginValidationError en esta versión de pytest.
    """
    plugin_manager = config.pluginmanager
    for name in ("launch_ros", "launch_testing_ros_pytest_entrypoint"):
        plugin = plugin_manager.get_plugin(name)
        if plugin is not None:
            plugin_manager.unregister(plugin)
