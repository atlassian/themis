(function () {
  'use strict';

  var app = angular.module('app');

  app.controller('configCtrl', function($scope, restClient, appConfig) {

    var client = restClient;
    appConfig.section = 'general';
    $scope.saving = false;

    $scope.load = function() {
      $scope.loading = true;
      appConfig.getConfig()
      .then(function(config) {
        $scope.loading = false;
        $scope.$apply(function(){
          $scope.config = config;
        });
      }, function(err) {
        $scope.loading = false;
        console.log(err);
      });
    };

    $scope.save = function() {
      /* load config */
      $scope.saving = true;
      appConfig.setConfig($scope.config)
      .then(function(config) {
        $scope.$apply(function(){
          $scope.saving = false;
          $scope.config = config;
        });
      }, function(err) {
        $scope.$apply(function(){
          $scope.saving = false;
        });
        console.log(err);
      });
    };

    $scope.load();

  });

})();