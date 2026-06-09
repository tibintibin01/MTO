from backend.routes.properties import router


def test_unspecified_route_is_before_property_id_route():
    paths = [route.path for route in router.routes]
    assert "/properties/unspecified" in paths
    assert "/properties/{property_id}" in paths
    assert paths.index("/properties/unspecified") < paths.index("/properties/{property_id}")