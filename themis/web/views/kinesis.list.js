(function () {
  'use strict';

  var app = angular.module('app');

  app.controller('kinesisAutoscaleCtrl', function($scope, appConfig, appUtils) {

    appConfig.section = 'general';

    $scope.$watch('stream.autoscale', function(newVal, oldVal) {
      if(typeof(oldVal) != 'undefined') {
        appConfig.getConfigValue('autoscaling_kinesis_streams').then(function(autoscaleStreams) {
        	autoscaleStreams = autoscaleStreams.split(/\s*,\s*/);
        	appUtils.arrayRemove(autoscaleStreams, $scope.stream.id);
          if(newVal) {
            autoscaleStreams.push($scope.stream.id);
          }
          autoscaleStreams = autoscaleStreams.join(',');
          appConfig.setConfigValue('autoscaling_kinesis_streams', autoscaleStreams).then(function(config) {
            console.log("Successfully updated configuration.");
          });
        });
      }
    });

    $scope.$watch('stream.monitoring', function(newVal, oldVal) {
      if(typeof(oldVal) != 'undefined') {
        var params = {
          section: 'kinesis',
          resource: $scope.stream.id
        };
        newVal = '' + newVal;
        appConfig.setConfigValue('enable_enhanced_monitoring', newVal, null, params).then(function(config) {
          console.log('Successfully updated configuration.');
        });
      }
    });

  });

  app.controller('kinesisListCtrl', function($scope, restClient, appConfig) {

    var client = restClient;
    appConfig.section = 'general';

    var loadStreamData = function(data) {
      $scope.$apply(function() {
        $scope.streams = data.results;
        appConfig.getConfigValue('autoscaling_kinesis_streams')
        .then(function(autoscaleStreams) {
          autoscaleStreams = autoscaleStreams.split(/\s*,\s*/);
          $scope.streams.forEach(function(stream) {
            stream.autoscale = autoscaleStreams.indexOf(stream.id) >= 0;
            stream.monitoring = stream.enhanced_monitoring.length > 0;
          });
          $scope.$apply();
        });
      });
    };

    $scope.refresh = function() {
      client.then(function(client) {
        $scope.loading = true;

        /* load current state */
        client.default.getKinesisStreams().then(function(obj) {
          $scope.loading = false;
          loadStreamData(obj.obj);
        }, function(err) {
          $scope.loading = false;
          console.log(err);
        });

      });
    };

    $scope.refresh();

  });

})();
