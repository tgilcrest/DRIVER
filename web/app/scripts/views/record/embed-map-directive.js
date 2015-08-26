(function () {
    'use strict';

    var stamenTonerAttribution = 'Map tiles by <a href="http://stamen.com">Stamen Design</a>, under <a href="http://creativecommons.org/licenses/by/3.0">CC BY 3.0</a>. Data by <a href="http://openstreetmap.org">OpenStreetMap</a>, under <a href="http://www.openstreetmap.org/copyright">ODbL</a>.';

    function driverEmbedMap() {

        var map = null;
        var locationMarker = null;
        var scope = null;

        var module = {
            restrict: 'A',
            scope: false,
            replace: false,
            require: 'leafletMap',
            link: link
        };
        return module;

        function link(linkScope, element, attrs, controller) {
            scope = linkScope;
            controller.getMap().then(setUpMap);

            scope.$on('Record:LocationSelected', function(event, data) {
                setMarker(L.latLng(data.lat, data.lng));
            });

            // destroy map state when record is closed
            scope.$on('Record:Close', function() {
                map = null;
                locationMarker = null;
            });
        }

        // initialize map with baselayer and listen for click events
        function setUpMap(leafletMap) {
            map = leafletMap;
            var streets = new L.tileLayer('https://stamen-tiles-{s}.a.ssl.fastly.net/toner-lite/{z}/{x}/{y}.png',
                                          {attribution: stamenTonerAttribution});
            map.addLayer(streets, {detectRetina: true});

            map.on('click', function(e) {
                broadcastCoordinates(e.latlng);
                setMarker(e.latlng);
            });
        }

        // set marker location, or create marker at location if it does not exist yet
        function setMarker(latlng) {
            if (locationMarker) {
                locationMarker.setLatLng(latlng);
            } else {
                locationMarker = new L.marker(latlng, {draggable: true}).addTo(map);
                locationMarker.on('dragend', function() {
                    broadcastCoordinates(locationMarker.getLatLng());
                });
            }
        }

        // tell add-edit-controller.js when marker point set
        function broadcastCoordinates(latlng) {
            scope.$parent.$broadcast('Map:LocationSelected', [latlng.lat, latlng.lng]);
        }
    }

    angular.module('driver.views.record')
        .directive('driverEmbedMap', driverEmbedMap);

})();
